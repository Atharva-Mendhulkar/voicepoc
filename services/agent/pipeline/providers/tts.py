from config import settings


def create_tts_service():
    provider = settings.tts_provider.lower()

    if provider == "cartesia":
        from pipecat.services.cartesia.tts import CartesiaTTSService

        return CartesiaTTSService(
            api_key=settings.cartesia_api_key,
            voice_id=settings.cartesia_voice_id,
            sample_rate=24000,
        )

    elif provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model="eleven_turbo_v2_5",
            sample_rate=22050,
        )

    else:
        raise ValueError(
            f"Unknown TTS provider: {provider!r}. Valid options: cartesia, elevenlabs"
        )
