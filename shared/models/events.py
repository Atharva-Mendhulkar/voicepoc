from pydantic import BaseModel
from typing import Any, Dict

class RuntimeEvent(BaseModel):
    session_id: str
    mode: int
    type: str
    relative_ms: float
    data: Dict[str, Any] = {}
