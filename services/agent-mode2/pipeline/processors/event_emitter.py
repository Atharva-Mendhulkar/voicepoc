import asyncio
import json
import logging
from typing import Optional
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    TextFrame,
    LLMFullResponseEndFrame,
    InterruptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    TTSStartedFrame,
    CancelFrame,
)

from shared.telemetry import TelemetryEmitter

logger = logging.getLogger("uvicorn")


class EventEmitterProcessor(FrameProcessor):
    def __init__(self, transport, telemetry: TelemetryEmitter):
        super().__init__()
        self.transport = transport
        self.telemetry = telemetry
        self.first_token_seen = False
        self.first_audio_seen = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            asyncio.create_task(self.telemetry.emit("user.speech.start", {}))
        elif isinstance(frame, UserStoppedSpeakingFrame):
            asyncio.create_task(self.telemetry.emit("user.speech.commit", {}))
        elif isinstance(frame, TranscriptionFrame):
            asyncio.create_task(self.transport.send_message(
                json.dumps({"type": "transcription", "text": frame.text, "is_final": True})
            ))
            asyncio.create_task(self.telemetry.emit("user.transcript.final", {"text": frame.text}))
            self.first_token_seen = False
            self.first_audio_seen = False
        elif isinstance(frame, InterruptionFrame):
            asyncio.create_task(self.telemetry.emit("interruption.detected", {}))
            asyncio.create_task(self.transport.send_message(
                json.dumps({"type": "interruption", "status": "cancelled"})
            ))
        elif isinstance(frame, CancelFrame):
            asyncio.create_task(self.telemetry.emit("interruption.completed", {"status": "cancelled"}))
        elif isinstance(frame, TextFrame):
            if not self.first_token_seen:
                asyncio.create_task(self.telemetry.emit("llm.first_token", {"token": frame.text}))
                self.first_token_seen = True
            asyncio.create_task(self.transport.send_message(
                json.dumps({"type": "transcription", "participant": "agent", "text": frame.text})
            ))
        elif isinstance(frame, TTSStartedFrame):
            if not self.first_audio_seen:
                asyncio.create_task(self.telemetry.emit("tts.first_audio", {}))
                self.first_audio_seen = True
        elif isinstance(frame, LLMFullResponseEndFrame):
            asyncio.create_task(self.telemetry.emit("llm.complete", {}))
