import time
import asyncio
import json
import logging
from typing import Any, Dict, Optional
from shared.redis_client import redis_client

logger = logging.getLogger("uvicorn")

class TelemetryEmitter:
    def __init__(self, session_id: str, mode_id: int, runtime_name: str):
        self.session_id = session_id
        self.mode_id = mode_id
        self.runtime_name = runtime_name
        self.session_start_ns = time.time_ns()
        self.trace_ids: Dict[str, str] = {}
        self.timing_checkpoints: Dict[str, float] = {}

    def set_trace_id(self, context_id: str, trace_id: str):
        self.trace_ids[context_id] = trace_id

    def record_checkpoint(self, key: str):
        self.timing_checkpoints[key] = time.time()

    def get_latency_ms(self, start_key: str) -> float:
        if start_key in self.timing_checkpoints:
            return round((time.time() - self.timing_checkpoints[start_key]) * 1000, 2)
        return 0.0

    async def emit(self, event_type: str, payload: Dict[str, Any] = {}, latency_ms: float = 0.0, context_id: Optional[str] = None):
        trace_id = self.trace_ids.get(context_id, self.session_id) if context_id else self.session_id
        event = {
            "timestamp_ns": time.time_ns(),
            "session_id": self.session_id,
            "mode_id": self.mode_id,
            "runtime": self.runtime_name,
            "trace_id": trace_id,
            "event_type": event_type,
            "latency_ms": latency_ms,
            "payload": json.dumps(payload)
        }
        stream_name = f"vrep:events:{self.session_id}:{self.mode_id}"
        try:
            # Also broadcast clean version for event-bridge
            cleaned_event = {
                "type": event_type,
                "relative_ms": time.time(),
                "text": payload.get("text", ""),
                "tool": payload.get("tool", ""),
                "args": payload.get("args", {}),
                "data": payload
            }
            await redis_client.xadd(stream_name, {k: str(v) for k, v in event.items()})
        except Exception as e:
            logger.error(f"Failed to emit telemetry event {event_type}: {e}")

