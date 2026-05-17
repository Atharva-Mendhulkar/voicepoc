import aiohttp
import json
import base64
import logging
import asyncio
from config import settings

logger = logging.getLogger("uvicorn")

class RawCartesiaTTS:
    def __init__(self, api_key: str, voice_id: str):
        self.api_key = api_key
        self.voice_id = voice_id
        self.session = None
        self.ws = None
        self.queues = {}
        self._receive_task = None
        self._closed = False

    async def connect(self):
        url = f"wss://api.cartesia.ai/tts/websocket?api_key={self.api_key}&cartesia_version=2024-06-10"
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(url)
        self._closed = False
        self._receive_task = asyncio.create_task(self._receiver())
        logger.info("RawCartesiaTTS WebSocket connected successfully (sonic-english, language=en)")

    async def _receiver(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    resp = json.loads(msg.data)
                    ctx = resp.get("context_id")
                    if not ctx or ctx not in self.queues:
                        continue
                    type_ = resp.get("type")
                    if type_ == "chunk":
                        data = resp.get("data")
                        if data:
                            pcm = base64.b64decode(data)
                            await self.queues[ctx].put(pcm)
                    elif type_ == "done":
                        await self.queues[ctx].put(None)
                    elif type_ == "error":
                        logger.error(f"Cartesia error in ctx {ctx}: {resp}")
                        await self.queues[ctx].put(None)
        except Exception as e:
            if not self._closed:
                logger.error(f"Cartesia receiver exception: {e}")

    async def send_text(self, text: str, context_id: str, continue_transcript: bool = True):
        if self._closed or not self.ws or self.ws.closed:
            return
        if context_id not in self.queues:
            self.queues[context_id] = asyncio.Queue()

        msg = {
            "transcript": text,
            "continue": continue_transcript,
            "context_id": context_id,
            "model_id": "sonic-english",
            "language": "en",
            "voice": {"mode": "id", "id": self.voice_id},
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": 24000
            },
            "add_timestamps": False
        }
        await self.ws.send_json(msg)

    async def receive_audio_chunks(self, context_id: str):
        if context_id not in self.queues:
            self.queues[context_id] = asyncio.Queue()
        q = self.queues[context_id]
        while True:
            chunk = await q.get()
            if chunk is None:
                break
            yield chunk

    async def cancel(self, context_id: str):
        if self._closed or not self.ws or self.ws.closed:
            return
        logger.info(f"Cancelling Cartesia TTS for context {context_id}")
        cancel_msg = {"context_id": context_id, "cancel": True}
        await self.ws.send_json(cancel_msg)
        if context_id in self.queues:
            await self.queues[context_id].put(None)

    async def close(self):
        self._closed = True
        if self._receive_task:
            self._receive_task.cancel()
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session:
            await self.session.close()
        logger.info("RawCartesiaTTS closed cleanly")


def create_tts_service():
    provider = settings.tts_provider.lower()

    if provider == "cartesia":
        from pipecat.services.cartesia.tts import CartesiaTTSService

        return CartesiaTTSService(
            api_key=settings.cartesia_api_key,
            settings=CartesiaTTSService.Settings(
                model="sonic-english",
                voice=settings.cartesia_voice_id,
                language="en",
            ),
            sample_rate=24000,
            encoding="pcm_s16le",
            container="raw",
        )

    elif provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key,
            settings=ElevenLabsTTSService.Settings(
                voice=settings.elevenlabs_voice_id,
                model="eleven_turbo_v2_5",
            ),
            sample_rate=24000,
        )

    else:
        raise ValueError(
            f"Unknown TTS provider: {provider!r}. Valid options: cartesia, elevenlabs"
        )
