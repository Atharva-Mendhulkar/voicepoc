from config import settings


def create_stt_service():
    provider = settings.stt_provider.lower()

    if provider == "deepgram":
        from pipecat.services.deepgram.stt import DeepgramSTTService, LiveOptions

        return DeepgramSTTService(
            api_key=settings.deepgram_api_key,
            live_options=LiveOptions(
                model="nova-2",
                language=settings.agent_language,
                smart_format=True,
                punctuate=True,
                interim_results=True,
                utterance_end_ms="1000",
                vad_events=True,
            ),
        )

    elif provider == "google_chirp":
        from pipecat.services.google.stt import GoogleSTTService
        import os

        return GoogleSTTService(
            credentials_file=os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS", "/app/gcp-credentials.json"
            ),
            language_code=settings.agent_language or "en-IN",
        )

    else:
        raise ValueError(
            f"Unknown STT provider: {provider!r}. Valid options: deepgram, google_chirp"
        )
