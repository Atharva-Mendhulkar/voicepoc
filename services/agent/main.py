import uuid
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import livekit.api as livekit_api

from config import settings
from pipeline.agent import run_agent_session

logger = logging.getLogger("uvicorn")

_sessions: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Clean shutdown — cancel all active sessions
    for session_id, task in list(_sessions.items()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("All sessions cancelled.")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class JoinRequest(BaseModel):
    user_identity: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
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
    session_id = str(uuid.uuid4())
    room_name = f"room-{session_id}"

    # Mint user token
    user_token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(req.user_identity)
        .with_grants(livekit_api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )

    # Mint agent token
    agent_token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"agent-{session_id}")
        .with_grants(livekit_api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )

    # Spawn the pipeline as a background task
    task = asyncio.create_task(
        run_agent_session(session_id, room_name, agent_token),
        name=f"session-{session_id}",
    )
    _sessions[session_id] = task

    def _cleanup(t):
        _sessions.pop(session_id, None)
        logger.info(f"session.end session_id={session_id}")

    task.add_done_callback(_cleanup)

    logger.info(f"session.start session_id={session_id} room={room_name}")

    return {
        "session_id": session_id,
        "room_name": room_name,
        "token": user_token,
        "livekit_url": settings.livekit_public_url,
    }


@app.delete("/session/{session_id}")
async def end_session(session_id: str):
    task = _sessions.get(session_id)
    if not task:
        return {"error": "Session not found"}
    task.cancel()
    return {"status": "cancelled", "session_id": session_id}
