import asyncio
import json
import logging
import time
from datetime import date

from livekit import rtc
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.livekit.transport import LiveKitTransport, LiveKitParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.frames.frames import LLMMessagesAppendFrame, TextFrame

from shared.config import settings
from shared.tools.handlers import execute_tool
from shared.tools.registry import get_tools_schema
from shared.telemetry import TelemetryEmitter
from pipeline.processors.event_emitter import EventEmitterProcessor

logger = logging.getLogger("uvicorn")

SYSTEM_PROMPT = """You are a helpful voice appointment assistant. Keep responses short — 1-2 sentences maximum for voice.
CRITICAL: You are allowed to speak in English, Hindi, or Hinglish depending on what the user speaks. Speak naturally in a conversational tone.

APPOINTMENT BOOKING RULES (follow exactly):
1. When a user requests an appointment, collect date AND time before calling any tool.
2. Call check_availability with the exact date (YYYY-MM-DD) and time (HH:MM 24h).
3. If available: say the slot is free and ask the user to confirm. Wait for their answer.
4. If the user confirms (says yes/confirm/book/okay): call book_appointment immediately.
5. If the user declines: ask if they want a different time.
6. NEVER say an appointment is confirmed without calling book_appointment first.
7. NEVER call book_appointment without a prior check_availability that returned available=true.

Today's date: {today}"""


async def run_pipecat_session(session_id: str, room_name: str, agent_token: str):
    logger.info(f"[MODE 2 - PIPECAT ONLY] Initializing session={session_id}")
    telemetry = TelemetryEmitter(session_id, 2, "pipecat")
    asyncio.create_task(telemetry.emit("session.lifecycle", {"status": "started"}))

    transport = LiveKitTransport(
        url=settings.livekit_url,
        token=agent_token,
        room_name=room_name,
        params=LiveKitParams(
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
        ),
    )

    stt = DeepgramSTTService(api_key=settings.deepgram_api_key)
    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSService.Settings(model="sonic-english", voice=settings.cartesia_voice_id or "248be419-c632-4f23-adf1-5324ed7dbf1d")
    )
    llm = OpenAILLMService(
        api_key=settings.openai_api_key,
        settings=OpenAILLMService.Settings(model="gpt-4o-mini")
    )

    pending_appointment = {"date": "", "time": ""}

    # Register tools
    ts = ToolsSchema(standard_tools=get_tools_schema())

    async def _handle_check_availability(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"[MODE 2 TOOL] check_availability({args})")
        pending_appointment["date"] = args.get("date", "")
        pending_appointment["time"] = args.get("time", "")
        asyncio.create_task(telemetry.emit("tool.call.start", {"tool": "check_availability", "args": args}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_call", "tool": "check_availability", "args": args})
        ))
        res = await execute_tool("check_availability", args)
        asyncio.create_task(telemetry.emit("tool.call.complete", {"tool": "check_availability", "args": args, "result": res}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_result", "tool": "check_availability", "args": args, "result": res})
        ))
        await params.result_callback(res)

    async def _handle_book_appointment(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"[MODE 2 TOOL] book_appointment({args})")
        args["date"] = args.get("date") or pending_appointment.get("date", "")
        args["time"] = args.get("time") or pending_appointment.get("time", "")
        asyncio.create_task(telemetry.emit("tool.call.start", {"tool": "book_appointment", "args": args}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_call", "tool": "book_appointment", "args": args})
        ))
        res = await execute_tool("book_appointment", args)
        asyncio.create_task(telemetry.emit("tool.call.complete", {"tool": "book_appointment", "args": args, "result": res}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_result", "tool": "book_appointment", "args": args, "result": res})
        ))
        await params.result_callback(res)

    async def _handle_get_weather(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"[MODE 2 TOOL] get_weather({args})")
        asyncio.create_task(telemetry.emit("tool.call.start", {"tool": "get_weather", "args": args}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_call", "tool": "get_weather", "args": args})
        ))
        res = await execute_tool("get_weather", args)
        asyncio.create_task(telemetry.emit("tool.call.complete", {"tool": "get_weather", "args": args, "result": res}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_result", "tool": "get_weather", "args": args, "result": res})
        ))
        await params.result_callback(res)

    async def _handle_update_crm(params: FunctionCallParams):
        args = params.arguments
        logger.info(f"[MODE 2 TOOL] update_crm({args})")
        asyncio.create_task(telemetry.emit("tool.call.start", {"tool": "update_crm", "args": args}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_call", "tool": "update_crm", "args": args})
        ))
        res = await execute_tool("update_crm", args)
        asyncio.create_task(telemetry.emit("tool.call.complete", {"tool": "update_crm", "args": args, "result": res}))
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "tool_result", "tool": "update_crm", "args": args, "result": res})
        ))
        await params.result_callback(res)

    llm.register_function("check_availability", _handle_check_availability)
    llm.register_function("book_appointment", _handle_book_appointment)
    llm.register_function("get_weather", _handle_get_weather)
    llm.register_function("update_crm", _handle_update_crm)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(today=date.today().isoformat()),
        }
    ]

    context = LLMContext(messages=messages, tools=ts)
    user_agg, assistant_agg = LLMContextAggregatorPair(context)

    user_event_processor = EventEmitterProcessor(transport, telemetry)
    assistant_event_processor = EventEmitterProcessor(transport, telemetry)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_event_processor,
            user_agg,
            llm,
            tts,
            transport.output(),
            assistant_event_processor,
            assistant_agg,
        ]
    )

    task = PipelineTask(pipeline, params=PipelineParams())

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant_id):
        logger.info(f"[MODE 2] Participant {participant_id} joined LiveKit room")
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "mode_info", "mode": "pipecat", "phase": 2, "status": "conversational"})
        ))
        greeting = "Hello! I'm Agent. You're connected in Pipecat-Only mode. How can I help?"
        asyncio.create_task(telemetry.emit("tts.request.start", {"text": greeting}))
        await task.queue_frames([LLMMessagesAppendFrame([{"role": "assistant", "content": greeting}], run_llm=False), TextFrame(greeting)])
        asyncio.create_task(transport.send_message(
            json.dumps({"type": "transcription", "participant": "agent", "text": greeting})
        ))

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant_id, reason):
        logger.info(f"[MODE 2] Participant {participant_id} left room ({reason})")
        await task.cancel()

    runner = PipelineRunner()

    try:
        await runner.run(task)
    except asyncio.CancelledError:
        logger.info("[MODE 2] Pipeline cancelled")
    except Exception as e:
        logger.error(f"[MODE 2 Error] {e}")
        asyncio.create_task(telemetry.emit("pipeline.error", {"error": str(e)}))
    finally:
        asyncio.create_task(telemetry.emit("session.lifecycle", {"status": "closed"}))
