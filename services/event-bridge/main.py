import asyncio
import json
import logging
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from shared.redis_client import redis_client

app = FastAPI()
logger = logging.getLogger("uvicorn")

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.info(f"WebSocket client connected to session {session_id}")

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            try:
                self.active_connections[session_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        logger.info(f"WebSocket client disconnected from session {session_id}")

    async def broadcast(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            msg_str = json.dumps(message)
            disconnected = []
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_text(msg_str)
                except Exception:
                    disconnected.append(connection)
            for d in disconnected:
                self.disconnect(d, session_id)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)
    try:
        while True:
            # We just hold the connection open. Events are pushed via the redis consumer.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)

async def consume_redis_streams():
    logger.info("Starting Redis Streams consumer for event-bridge...")
    active_streams = {}
    
    # We poll all vrep:events:* streams
    while True:
        try:
            # Get all active streams keys
            keys = await redis_client.keys("vrep:events:*")
            if not keys:
                await asyncio.sleep(1)
                continue
                
            for k in keys:
                if k not in active_streams:
                    active_streams[k] = "0" # Start reading from beginning for new streams
            
            # Remove expired streams
            for k in list(active_streams.keys()):
                if k not in keys:
                    del active_streams[k]
                    
            while True:
                # Need to update keys list occasionally
                if int(time.time()) % 10 == 0:
                    break
                    
                messages = await redis_client.xread(active_streams, count=100, block=1000)
                if messages:
                    for stream_name, stream_msgs in messages:
                        session_id = stream_name.split(":")[2]
                        for msg_id, msg_data in stream_msgs:
                            active_streams[stream_name] = msg_id
                            
                            payload_str = msg_data.get("payload", "{}")
                            try:
                                payload = json.loads(payload_str)
                            except Exception:
                                payload = {}

                            ts_ns = int(msg_data.get("timestamp_ns", 0))
                            relative_ms = ts_ns / 1_000_000_000.0 if ts_ns else time.time()

                            cleaned_data = {
                                "type": msg_data.get("event_type", "unknown"),
                                "relative_ms": relative_ms,
                                "text": payload.get("text", payload.get("token", "")),
                                "tool": payload.get("tool", ""),
                                "args": payload.get("args", {}),
                                "data": payload,
                                "status": payload.get("status", ""),
                            }

                            await manager.broadcast(session_id, cleaned_data)
                
        except Exception as e:
            logger.error(f"Redis consumer error: {e}")
            await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(consume_redis_streams())
