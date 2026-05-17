from dataclasses import dataclass

@dataclass
class UtteranceCompleteEvent:
    text: str
    turn_id: str

@dataclass
class InterruptionEvent:
    turn_id: str
    reason: str = "user_speaking"

@dataclass
class AgentSpeakingStartEvent:
    turn_id: str

@dataclass
class AgentSpeakingEndEvent:
    turn_id: str
