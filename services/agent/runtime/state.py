import logging
from dataclasses import dataclass, field

logger = logging.getLogger("uvicorn")

@dataclass
class RuntimeState:
    session_id: str
    room_name: str
    user_speaking: bool = False
    agent_speaking: bool = False
    chat_history: list[dict[str, str]] = field(default_factory=list)
    current_context_id: str | None = None
    pending_appointment: dict = field(default_factory=dict)

    def add_user_message(self, text: str):
        self.chat_history.append({"role": "user", "content": text})
        logger.info(f"[STATE] User turn added: {text}")

    def add_assistant_message(self, text: str):
        self.chat_history.append({"role": "assistant", "content": text})
        logger.info(f"[STATE] Assistant turn added: {text}")
