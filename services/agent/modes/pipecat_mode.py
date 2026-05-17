import logging
from pipeline.agent import run_agent_session

logger = logging.getLogger("uvicorn")

async def run_session(session_id: str, room_name: str, agent_token: str):
    logger.info(f"[PIPECAT MODE] Running session={session_id}")
    await run_agent_session(session_id, room_name, agent_token)
