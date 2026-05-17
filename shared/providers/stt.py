import asyncio
import json
import logging
import aiohttp
from shared.config import settings

logger = logging.getLogger("uvicorn")

class DeepgramSTT:
    def __init__(self, api_key: str, callback):
        self._api_key = api_key
        self._callback = callback  # async def callback(transcript: str, is_final: bool)
        self._ws = None
        self._session = None
        self._buffer = b""
        self._closed = False

    async def connect(self):
        # Locked strictly to English (en-US) with 50ms endpointing and vad_events for ultra-low latency
        url = "wss://api.deepgram.com/v1/listen?model=nova-2&language=en-US&encoding=linear16&sample_rate=48000&channels=1&interim_results=true&endpointing=50&vad_events=true&smart_format=true"
        headers = {"Authorization": f"Token {self._api_key}"}
        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(url, headers=headers)
            self._closed = False
            logger.info("Deepgram STT WebSocket connected successfully (en-US, endpointing=50ms, vad_events=true)")
            asyncio.create_task(self._receive_transcripts())
        except Exception as e:
            logger.error(f"Deepgram connection failed: {e}")
            self._closed = True

    async def send_audio(self, pcm_data: bytes):
        if self._closed or not self._ws or self._ws.closed:
            return

        self._buffer += pcm_data
        # 50ms chunks @ 48kHz (4800 bytes) for minimal packet buffering delay
        if len(self._buffer) >= 4800:
            try:
                await self._ws.send_bytes(self._buffer)
                self._buffer = b""
            except Exception as e:
                logger.error(f"Deepgram send error: {e}")
                self._closed = True

    async def _receive_transcripts(self):
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    resp = json.loads(msg.data)
                    if isinstance(resp, dict) and resp.get("type") == "Results":
                        channel = resp.get("channel")
                        if isinstance(channel, dict):
                            alts = channel.get("alternatives")
                            if isinstance(alts, list) and len(alts) > 0 and isinstance(alts[0], dict):
                                transcript = alts[0].get("transcript", "")
                                if transcript:
                                    is_final = resp.get("is_final", False)
                                    await self._callback(transcript, is_final)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            if not self._closed:
                logger.error(f"STT receive error: {e}")
        finally:
            self._closed = True

    async def close(self):
        self._closed = True
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()


def create_stt_service():
    provider = settings.stt_provider.lower()

    if provider == "deepgram":
        from pipecat.services.deepgram.stt import DeepgramSTTService

        return DeepgramSTTService(
            api_key=settings.deepgram_api_key,
            settings=DeepgramSTTService.Settings(
                model="nova-2",
                language="en-US",
                smart_format=True,
                punctuate=True,
                interim_results=True,
                utterance_end_ms=700,
            ),
        )

    elif provider == "google_chirp":
        from pipecat.services.google.stt import GoogleSTTService
        import os

        return GoogleSTTService(
            credentials_file=os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS", "/app/gcp-credentials.json"
            ),
            language_code="en-US",
        )

    else:
        raise ValueError(
            f"Unknown STT provider: {provider!r}. Valid options: deepgram, google_chirp"
        )
