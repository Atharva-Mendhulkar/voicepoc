import uuid
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import livekit.api as livekit_api

from shared.config import settings
from pipeline.agent import run_pipecat_session

logger = logging.getLogger("uvicorn")
_sessions: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AgentOS starting — mode=PIPECAT (Mode 2)")
    yield
    for task in list(_sessions.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("All sessions drained.")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class JoinRequest(BaseModel):
    user_identity: str
    session_id: str | None = None


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "pipecat",
        "mode_id": 2,
        "providers": {
            "stt": settings.stt_provider,
            "tts": settings.tts_provider,
            "llm": settings.llm_provider,
        },
        "active_sessions": len(_sessions),
    }


@app.get("/sessions")
async def list_sessions():
    return {"sessions": list(_sessions.keys()), "count": len(_sessions)}


@app.post("/session/join")
async def join_session(req: JoinRequest):
    session_id = req.session_id or str(uuid.uuid4())
    room_name = f"room-{session_id}"

    user_token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(req.user_identity)
        .with_grants(livekit_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))
        .to_jwt()
    )
    agent_token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"agent-{session_id}")
        .with_grants(livekit_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
            can_update_own_metadata=True,
            agent=True,
        ))
        .to_jwt()
    )

    task = asyncio.create_task(
        run_pipecat_session(session_id, room_name, agent_token),
        name=f"session-{session_id}",
    )
    _sessions[session_id] = task
    task.add_done_callback(lambda t: _sessions.pop(session_id, None))

    logger.info(f"session.start mode=pipecat id={session_id}")
    return {
        "session_id": session_id,
        "room_name": room_name,
        "token": user_token,
        "livekit_url": settings.livekit_public_url,
        "mode": "pipecat",
        "mode_id": 2,
    }


@app.delete("/session/{session_id}")
async def end_session(session_id: str):
    task = _sessions.get(session_id)
    if not task:
        return {"error": "not found"}
    task.cancel()
    return {"cancelled": session_id}
