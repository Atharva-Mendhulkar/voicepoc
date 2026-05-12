import asyncio
import json
import logging

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TextFrame, TranscriptionFrame, LLMFullResponseEndFrame, TTSTextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    LLMAssistantAggregatorParams
)
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport
from pipecat.observers.base_observer import BaseObserver, FramePushed

from config import settings
from pipeline.providers.llm import create_llm_service
from pipeline.providers.stt import create_stt_service
from pipeline.providers.tts import create_tts_service

logger = logging.getLogger("uvicorn")


async def run_agent_session(session_id: str, room_name: str, agent_token: str):
    logger.info(f"pipeline.init session_id={session_id}")

    transport = LiveKitTransport(
        url=settings.livekit_url,
        token=agent_token,
        room_name=room_name,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_enabled=True,
            audio_out_sample_rate=24000,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    stop_secs=0.5,
                    min_volume=0.2,
                    confidence=0.7,
                )
            ),
            vad_audio_passthrough=True,
        ),
    )

    stt = create_stt_service()
    tts = create_tts_service()
    llm = create_llm_service()

    # Context holds the conversation history
    context = LLMContext()
    
    # Modern pattern for context aggregators in 1.1.0
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_stop_timeout=0.6
        )
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    # ── Greeting ──────────────────────────────────────────────────────────────
    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        # participant can be a string (identity) or an object depending on the version
        identity = getattr(participant, "identity", str(participant))
        logger.info(f"participant.joined session_id={session_id} identity={identity}")
        # In 1.1.0, capture is handled automatically by transport.input() or room settings
        
        # Send a direct text greeting (bypasses STT/LLM — instant TTS)
        greeting = TextFrame("Namaste! I'm Aria. How can I help you today?")
        await task.queue_frames([greeting])

    # ── Transcript broadcast ───────────────────────────────────────────────────
    class TranscriptBroadcaster(BaseObserver):
        """Watches frames flowing through the pipeline and relays transcripts
        back to the browser via LiveKit data messages."""

        def __init__(self):
            super().__init__()
            self._last_agent_turn: list[str] = []

        async def on_push_frame(self, data: FramePushed):
            frame = data.frame
            
            # User said something
            if isinstance(frame, TranscriptionFrame) and frame.text.strip():
                payload = json.dumps(
                    {"type": "transcription", "participant": "user", "text": frame.text}
                )
                await transport.send_message(payload)
                logger.debug(f"transcript.user text={frame.text!r}")

            # Agent TTS text chunk
            if isinstance(frame, TTSTextFrame) and frame.text.strip():
                self._last_agent_turn.append(frame.text)

            # Agent turn finished — broadcast accumulated text
            if isinstance(frame, LLMFullResponseEndFrame):
                full_text = " ".join(self._last_agent_turn).strip()
                if full_text:
                    payload = json.dumps(
                        {"type": "transcription", "participant": "agent", "text": full_text}
                    )
                    await transport.send_message(payload)
                    logger.debug(f"transcript.agent text={full_text!r}")
                self._last_agent_turn = []

    task.add_observer(TranscriptBroadcaster())

    # ── Participant left ───────────────────────────────────────────────────────
    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, *args):
        logger.info(f"participant.left session_id={session_id}")
        await task.cancel()

    # ── Run ───────────────────────────────────────────────────────────────────
    runner = PipelineRunner()
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        logger.info(f"pipeline.cancelled session_id={session_id}")
    finally:
        logger.info(f"pipeline.done session_id={session_id}")
