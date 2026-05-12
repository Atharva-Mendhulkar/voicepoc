from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    # LiveKit
    livekit_url: str = "ws://livekit:7880"
    livekit_public_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    # Provider selection
    stt_provider: str = "deepgram"
    tts_provider: str = "cartesia"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"

    # STT keys
    deepgram_api_key: str = ""
    agent_language: str = "multi"

    # TTS keys
    cartesia_api_key: str = ""
    cartesia_voice_id: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""

    # LLM keys
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""

    # Infra
    redis_url: str = "redis://redis:6379"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

settings = Settings()