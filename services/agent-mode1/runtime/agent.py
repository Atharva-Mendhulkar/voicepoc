import asyncio
import json
import logging
import time
from datetime import date

from livekit import rtc
from livekit.agents import llm, voice
from livekit.agents.voice import Agent as VoicePipelineAgent
from livekit.plugins import openai, deepgram, cartesia, silero

from shared.config import settings
from shared.tools.handlers import execute_tool
from shared.telemetry import TelemetryEmitter

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


class AppointmentTools(llm.Toolset):
    def __init__(self, room: rtc.Room, telemetry: TelemetryEmitter):
        super().__init__(id="appt_tools")
        self.room = room
        self.telemetry = telemetry
        self.pending_date = ""
        self.pending_time = ""

    @llm.function_tool(description="Check availability for a specific date and time")
    async def check_availability(self, date: str, time: str):
        self.pending_date = date
        self.pending_time = time
        args = {"date": date, "time": time}
        asyncio.create_task(self.telemetry.emit("tool.call.start", {"tool": "check_availability", "args": args}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_call", "tool": "check_availability", "args": args}).encode()
        )
        res = await execute_tool("check_availability", args)
        asyncio.create_task(self.telemetry.emit("tool.call.complete", {"tool": "check_availability", "args": args, "result": res}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_result", "tool": "check_availability", "args": args, "result": res}).encode()
        )
        return json.dumps(res)

    @llm.function_tool(description="Book an appointment after confirming availability")
    async def book_appointment(self, date: str = "", time: str = "", name: str = "Guest"):
        d = date or self.pending_date
        t = time or self.pending_time
        args = {"date": d, "time": t, "name": name}
        asyncio.create_task(self.telemetry.emit("tool.call.start", {"tool": "book_appointment", "args": args}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_call", "tool": "book_appointment", "args": args}).encode()
        )
        res = await execute_tool("book_appointment", args)
        asyncio.create_task(self.telemetry.emit("tool.call.complete", {"tool": "book_appointment", "args": args, "result": res}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_result", "tool": "book_appointment", "args": args, "result": res}).encode()
        )
        return json.dumps(res)

    @llm.function_tool(description="Get current weather for a city")
    async def get_weather(self, city: str):
        args = {"city": city}
        asyncio.create_task(self.telemetry.emit("tool.call.start", {"tool": "get_weather", "args": args}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_call", "tool": "get_weather", "args": args}).encode()
        )
        res = await execute_tool("get_weather", args)
        asyncio.create_task(self.telemetry.emit("tool.call.complete", {"tool": "get_weather", "args": args, "result": res}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_result", "tool": "get_weather", "args": args, "result": res}).encode()
        )
        return json.dumps(res)

    @llm.function_tool(description="Update CRM customer records")
    async def update_crm(self, field: str, value: str):
        args = {"field": field, "value": value}
        asyncio.create_task(self.telemetry.emit("tool.call.start", {"tool": "update_crm", "args": args}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_call", "tool": "update_crm", "args": args}).encode()
        )
        res = await execute_tool("update_crm", args)
        asyncio.create_task(self.telemetry.emit("tool.call.complete", {"tool": "update_crm", "args": args, "result": res}))
        await self.room.local_participant.publish_data(
            json.dumps({"type": "tool_result", "tool": "update_crm", "args": args, "result": res}).encode()
        )
        return json.dumps(res)


async def run_livekit_session(session_id: str, room_name: str, agent_token: str):
    logger.info(f"[MODE 1 - LIVEKIT ONLY] Initializing session={session_id}")
    telemetry = TelemetryEmitter(session_id, 1, "livekit")
    asyncio.create_task(telemetry.emit("session.lifecycle", {"status": "started"}))

    room = rtc.Room()
    appt_tools = AppointmentTools(room, telemetry)

    agent = VoicePipelineAgent(
        vad=silero.VAD.load(min_silence_duration=0.1),
        stt=deepgram.STT(api_key=settings.deepgram_api_key),
        llm=openai.LLM(api_key=settings.openai_api_key, model="gpt-4o-mini"),
        tts=cartesia.TTS(api_key=settings.cartesia_api_key, voice="sonic-english"),
        tools=[appt_tools],
        instructions=SYSTEM_PROMPT.format(today=date.today().isoformat()),
        allow_interruptions=True,
    )

    @room.on("disconnected")
    def on_disconnected():
        logger.info(f"[MODE 1] Room {room_name} disconnected")
        asyncio.create_task(telemetry.emit("session.lifecycle", {"status": "closed"}))

    try:
        await room.connect(settings.livekit_url, agent_token)
        logger.info(f"[MODE 1] Connected to room {room_name}")
        session = voice.AgentSession()
        await session.start(agent, room=room)

        @session.on("user_input_transcribed")
        def on_user_input_transcribed(event):
            if getattr(event, "is_final", False):
                text = getattr(event, "transcript", "")
                asyncio.create_task(telemetry.emit("user.speech.commit", {"text": text}))
                asyncio.create_task(telemetry.emit("user.transcript.final", {"text": text}))
                asyncio.create_task(room.local_participant.publish_data(
                    json.dumps({"type": "transcription", "text": text, "is_final": True}).encode()
                ))

        @session.on("agent_state_changed")
        def on_agent_state_changed(event):
            state = getattr(event, "new_state", "")
            if str(state).lower() == "speaking":
                asyncio.create_task(telemetry.emit("tts.first_audio", {}))

        await room.local_participant.publish_data(
            json.dumps({"type": "mode_info", "mode": "livekit", "phase": 2, "status": "conversational"}).encode()
        )
        greeting = "Hello! I'm Agent. You're connected in LiveKit-Only mode. How can I help?"
        asyncio.create_task(telemetry.emit("tts.request.start", {"text": greeting}))
        session.say(greeting)
        await room.local_participant.publish_data(
            json.dumps({"type": "transcription", "participant": "agent", "text": greeting}).encode()
        )

        participant_joined = False
        wait_time = 0
        while True:
            await asyncio.sleep(1)
            wait_time += 1
            if len(room.remote_participants) > 0:
                participant_joined = True

            if participant_joined and len(room.remote_participants) == 0:
                logger.info("[MODE 1] Room empty, draining session")
                break
            elif not participant_joined and wait_time > 30:
                logger.info("[MODE 1] Timeout waiting for participant")
                break

    except asyncio.CancelledError:
        logger.info("[MODE 1] Session cancelled")
    except Exception as e:
        logger.error(f"[MODE 1 Error] {e}")
        asyncio.create_task(telemetry.emit("pipeline.error", {"error": str(e)}))
    finally:
        await room.disconnect()
