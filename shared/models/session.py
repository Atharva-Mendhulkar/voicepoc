from pydantic import BaseModel
from typing import Optional

class SessionJoinRequest(BaseModel):
    user_identity: str
    mode: int = 2
    
class SessionJoinResponse(BaseModel):
    session_id: str
    room_name: str
    token: str
    livekit_url: str
    mode: int
