import logging
from runtime.session import RealtimeSession

logger = logging.getLogger("uvicorn")

async def run_session(session_id: str, room_name: str, agent_token: str):
    logger.info(f"[HYBRID MODE - RUNTIME] Initializing session={session_id}")
    session = RealtimeSession(session_id, room_name, agent_token)
    await session.run()
