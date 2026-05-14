import asyncio
import json
import logging
import time

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

# Optimized System Prompt for Voice Latency
SYSTEM_PROMPT = """You are Aria, a fast and helpful AI voice assistant. 
CRITICAL: Be extremely concise. Use 10-15 words MAXIMUM per response. 
Avoid lists, bullet points, or long explanations. 
Speak naturally like a human in a quick conversation. 
If the user speaks Hindi, respond in simple Hindi or Hinglish."""


async def run_agent_session(session_id: str, room_name: str, agent_token: str):
    logger.info(f"pipeline.init session_id={session_id}")

    # Latency Tuning (Aggressive):
    vad_stop_secs = 0.3 
    
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
                    stop_secs=vad_stop_secs,
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

    # Initialize context with System Prompt
    context = LLMContext([{"role": "system", "content": SYSTEM_PROMPT}])
    
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_stop_timeout=0.4 # Slightly above stop_secs for stability
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

    @task.event_handler("on_metrics")
    async def on_metrics(task, metrics):
        logger.info(f"latency.metrics session_id={session_id} metrics={metrics}")

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        identity = getattr(participant, "identity", str(participant))
        logger.info(f"participant.joined session_id={session_id} identity={identity}")
        
        greeting = TextFrame("Namaste! I'm Aria. How can I help?")
        await task.queue_frames([greeting])

    class TranscriptBroadcaster(BaseObserver):
        def __init__(self):
            super().__init__()
            self._last_agent_turn: list[str] = []

        async def on_push_frame(self, data: FramePushed):
            frame = data.frame
            if isinstance(frame, TranscriptionFrame) and frame.text.strip():
                payload = json.dumps({"type": "transcription", "participant": "user", "text": frame.text})
                await transport.send_message(payload)
            if isinstance(frame, TTSTextFrame) and frame.text.strip():
                self._last_agent_turn.append(frame.text)
            if isinstance(frame, LLMFullResponseEndFrame):
                full_text = " ".join(self._last_agent_turn).strip()
                if full_text:
                    payload = json.dumps({"type": "transcription", "participant": "agent", "text": full_text})
                    await transport.send_message(payload)
                self._last_agent_turn = []

    task.add_observer(TranscriptBroadcaster())

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, *args):
        logger.info(f"participant.left session_id={session_id}")
        await task.cancel()

    runner = PipelineRunner()
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        logger.info(f"pipeline.cancelled session_id={session_id}")
    finally:
        logger.info(f"pipeline.done session_id={session_id}")
