from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx, uuid, time
from shared.redis_client import redis_client
from shared.models.session import SessionJoinRequest

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODE_BACKENDS = {
    1: "http://agent-mode1:8080", 
    2: "http://agent-mode2:8080", 
    3: "http://agent-mode3:8080"
}

@app.post("/session/join")
async def join_session(req: SessionJoinRequest):
    if req.mode not in MODE_BACKENDS:
        raise HTTPException(400, f"Invalid mode: {req.mode}")
    
    session_id = str(uuid.uuid4())
    
    await redis_client.hset(f"vrep:sessions:{session_id}", mapping={
        "mode": req.mode, "started_at": time.time(),
        "user_identity": req.user_identity, "status": "active"
    })
    await redis_client.expire(f"vrep:sessions:{session_id}", 86400)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{MODE_BACKENDS[req.mode]}/session/join",
            json={**req.dict(), "session_id": session_id}
        )
    
    return resp.json()
