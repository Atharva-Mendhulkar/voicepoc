from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    agent_mode: str = "hybrid"          # livekit | pipecat | hybrid

    livekit_url: str = "ws://livekit:7880"
    livekit_public_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    stt_provider: str = "deepgram"
    tts_provider: str = "cartesia"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"

    deepgram_api_key: str = ""
    agent_language: str = "multi"

    cartesia_api_key: str = ""
    cartesia_voice_id: str = "248be419-c632-4f23-adf1-5324ed7dbf1d"

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    redis_url: str = "redis://redis:6379"

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()