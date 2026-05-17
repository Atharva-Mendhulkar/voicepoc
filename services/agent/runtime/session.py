import asyncio
import json
import uuid
import re
import time
import logging
from livekit import rtc
from livekit.rtc import AudioStream

from config import settings
from runtime.transcript import TranscriptAggregator
from runtime.state import RuntimeState
from runtime.metrics import TurnMetrics
from pipeline.providers.llm import stream_llm
from pipeline.providers.tts import RawCartesiaTTS
from pipeline.providers.stt import DeepgramSTT
from tools.registry import TOOL_DEFINITIONS
from tools.handlers import execute_tool
from datetime import date

logger = logging.getLogger("uvicorn")

SYSTEM_PROMPT = """You are a helpful voice appointment assistant. Keep responses short — 1-2 sentences maximum for voice.
CRITICAL: Speak strictly in standard American English. NEVER use Hindi, Hinglish, or any other language.

APPOINTMENT BOOKING RULES (follow exactly):
1. When a user requests an appointment, collect date AND time before calling any tool.
2. Call check_availability with the exact date (YYYY-MM-DD) and time (HH:MM 24h).
3. If available: say the slot is free and ask the user to confirm. Wait for their answer.
4. If the user confirms (says yes/confirm/book/okay): call book_appointment immediately.
5. If the user declines: ask if they want a different time.
6. NEVER say an appointment is confirmed without calling book_appointment first.
7. NEVER call book_appointment without a prior check_availability that returned available=true.

Today's date: {today}"""

class SentenceChunker:
    def __init__(self):
        self.buffer = ""

    def add_token(self, token: str) -> list[str]:
        self.buffer += token
        sentences = []
        while True:
            match = re.search(r'([.?!]+(?:\s+|\n+|$))', self.buffer)
            if not match and len(self.buffer) > 35:
                match = re.search(r'([,;:](?:\s+|\n+|$))', self.buffer)

            if match and match.end() <= len(self.buffer):
                idx = match.end()
                sentence = self.buffer[:idx].strip()
                if sentence:
                    sentences.append(sentence)
                self.buffer = self.buffer[idx:]
            else:
                break
        return sentences

    def flush(self) -> str:
        s = self.buffer.strip()
        self.buffer = ""
        return s


class RealtimeSession:
    def __init__(self, session_id: str, room_name: str, agent_token: str):
        self.session_id = session_id
        self.room_name = room_name
        self.agent_token = agent_token
        self.room = rtc.Room()
        self.state = RuntimeState(session_id=session_id, room_name=room_name)
        self.aggregator = TranscriptAggregator()
        self.stt = DeepgramSTT(settings.deepgram_api_key, self.on_stt_result)
        self.tts = RawCartesiaTTS(settings.cartesia_api_key, settings.cartesia_voice_id)

        self.audio_source: rtc.AudioSource | None = None
        self.audio_tasks = set()
        self.silence_timer: asyncio.Task | None = None
        self.current_llm_task: asyncio.Task | None = None
        self.current_tts_task: asyncio.Task | None = None
        self.current_playback_task: asyncio.Task | None = None
        self.metrics: TurnMetrics | None = None

    def cancel_agent_tasks(self):
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()
        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()
        if self.current_playback_task and not self.current_playback_task.done():
            self.current_playback_task.cancel()
        if self.state.current_context_id:
            asyncio.create_task(self.tts.cancel(self.state.current_context_id))

    async def on_stt_result(self, transcript: str, is_final: bool):
        # Prevent breathing, mic clicks, or minor speaker bleed from causing accidental interruptions
        if self.state.agent_speaking and len(transcript.strip()) >= 3:
            logger.info(f"[INTERRUPTION] User spoke '{transcript}' while agent was talking! Cancelling agent turn.")
            self.cancel_agent_tasks()
            await self.room.local_participant.publish_data(
                json.dumps({"type": "interruption", "status": "cancelled"}).encode()
            )
            self.state.agent_speaking = False

        if is_final:
            self.aggregator.on_final(transcript)
            logger.info(f"STT [FINAL]: {transcript}")
            if self.metrics:
                self.metrics.record_stt_final()
        else:
            self.aggregator.on_partial(transcript)

        await self.room.local_participant.publish_data(
            json.dumps({"type": "transcription", "text": transcript, "is_final": is_final}).encode()
        )

        if self.silence_timer and not self.silence_timer.done():
            self.silence_timer.cancel()

        if self.aggregator.has_unflushed_finals():
            self.silence_timer = asyncio.create_task(self._wait_for_silence())

    async def _wait_for_silence(self):
        try:
            # Deepgram endpointing=50 already guarantees silence, so we only need a tiny 50ms buffer here
            await asyncio.sleep(0.05)
            await self.on_user_turn_complete()
        except asyncio.CancelledError:
            pass

    async def on_user_turn_complete(self):
        utterance = self.aggregator.flush()
        if not utterance:
            return

        self.state.add_user_message(utterance)
        context_id = str(uuid.uuid4())
        self.state.current_context_id = context_id
        self.metrics = TurnMetrics(turn_id=context_id, turn_start_time=time.time())
        self.metrics.record_stt_final()

        self.current_llm_task = asyncio.create_task(self._run_agent_turn(context_id))

    async def _run_agent_turn(self, context_id: str):
        self.state.agent_speaking = True
        self.current_playback_task = asyncio.create_task(self._audio_playback_loop(context_id))

        clean_history = []
        for h in self.state.chat_history[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                clean_history.append({"role": h["role"], "content": h["content"]})

        system_prompt = SYSTEM_PROMPT.format(today=date.today().isoformat())
        messages = [{"role": "system", "content": system_prompt}] + clean_history
        chunker = SentenceChunker()
        full_response = ""
        first_chunk = True
        executed_tools = []

        try:
            async for item in stream_llm(messages, tools=TOOL_DEFINITIONS):
                if item["type"] == "content":
                    token = item["content"]
                    if first_chunk and self.metrics:
                        self.metrics.record_llm_ttfb()
                        first_chunk = False

                    full_response += token
                    sentences = chunker.add_token(token)
                    for sentence in sentences:
                        logger.info(f"[LLM -> TTS] Queuing sentence: {sentence}")
                        await self.tts.send_text(sentence, context_id, continue_transcript=True)
                        await self.room.local_participant.publish_data(
                            json.dumps({"type": "transcription", "participant": "agent", "text": sentence}).encode()
                        )

                elif item["type"] == "tool_calls":
                    for tc in item["tool_calls"]:
                        name = tc["name"]
                        try:
                            args = json.loads(tc["arguments"])
                        except:
                            args = {}
                        logger.info(f"[HYBRID TOOL] Calling tool {name}({args})")
                        
                        # Update pending appointment state
                        if name == "check_availability":
                            self.state.pending_appointment["date"] = args.get("date")
                            self.state.pending_appointment["time"] = args.get("time")
                        elif name == "book_appointment":
                            # Enforce state carry-over
                            args["date"] = self.state.pending_appointment.get("date") or args.get("date", "")
                            args["time"] = self.state.pending_appointment.get("time") or args.get("time", "")
                            self.state.pending_appointment.clear()

                        # Emit UI tool call event BEFORE TTS speech starts so it renders in conversation order
                        await self.room.local_participant.publish_data(
                            json.dumps({"type": "tool_call", "tool": name, "args": args}).encode()
                        )
                        
                        # Instant verbal confirmation to cover API/LLM follow-up latency
                        filler = "Let me check that for you right now..."
                        if name == "check_availability":
                            filler = "Checking slot availability right now..."
                        elif name == "book_appointment":
                            filler = "Booking your appointment now..."
                        elif name == "get_weather":
                            filler = "Checking the latest weather report..."
                        elif name == "update_crm":
                            filler = "Updating the customer records now..."
                        
                        await self.tts.send_text(filler, context_id, continue_transcript=True)
                        await self.room.local_participant.publish_data(
                            json.dumps({"type": "transcription", "participant": "agent", "text": filler}).encode()
                        )
                        result = await execute_tool(name, args)
                        logger.info(f"[HYBRID TOOL] Result: {result}")
                        await self.room.local_participant.publish_data(
                            json.dumps({"type": "tool_result", "tool": name, "args": args, "result": result}).encode()
                        )
                        executed_tools.append({"call": tc, "args": args, "result": result})

            leftover = chunker.flush()
            if leftover:
                logger.info(f"[LLM -> TTS] Queuing leftover: {leftover}")
                await self.tts.send_text(leftover, context_id, continue_transcript=False)
                await self.room.local_participant.publish_data(
                    json.dumps({"type": "transcription", "participant": "agent", "text": leftover}).encode()
                )
            else:
                await self.tts.send_text("", context_id, continue_transcript=False)

            if full_response.strip():
                self.state.add_assistant_message(full_response.strip())

            if executed_tools:
                for t in executed_tools:
                    self.state.chat_history.append({
                        "role": "assistant",
                        "content": f"[Executed tool {t['call']['name']}]"
                    })
                    self.state.chat_history.append({
                        "role": "user",
                        "content": f"Tool {t['call']['name']} returned: {json.dumps(t['result'])}. Please tell me the result concisely."
                    })
                followup_id = str(uuid.uuid4())
                self.state.current_context_id = followup_id
                asyncio.create_task(self._run_agent_turn(followup_id))

        except asyncio.CancelledError:
            logger.info(f"[LLM] Cancelled for context {context_id}")
        except Exception as e:
            logger.error(f"[LLM Error] {e}")

    async def _audio_playback_loop(self, context_id: str):
        first_audio = True
        pcm_buffer = b""
        block_size = 9600

        try:
            async for pcm_chunk in self.tts.receive_audio_chunks(context_id):
                if first_audio and self.metrics:
                    self.metrics.record_tts_ttfb()
                    first_audio = False

                pcm_buffer += pcm_chunk
                while len(pcm_buffer) >= block_size:
                    to_play = pcm_buffer[:block_size]
                    pcm_buffer = pcm_buffer[block_size:]

                    samples = len(to_play) // 2
                    frame = rtc.AudioFrame(
                        data=to_play,
                        sample_rate=24000,
                        num_channels=1,
                        samples_per_channel=samples,
                    )
                    if self.audio_source:
                        await self.audio_source.capture_frame(frame)

                    await asyncio.sleep(0.18)

            if pcm_buffer:
                samples = len(pcm_buffer) // 2
                frame = rtc.AudioFrame(
                    data=pcm_buffer,
                    sample_rate=24000,
                    num_channels=1,
                    samples_per_channel=samples,
                )
                if self.audio_source:
                    await self.audio_source.capture_frame(frame)
                await asyncio.sleep((samples / 24000.0) * 0.9)

        except asyncio.CancelledError:
            logger.info(f"[Playback] Cancelled for context {context_id}")
        except Exception as e:
            logger.error(f"[Playback Error] {e}")
        finally:
            self.state.agent_speaking = False
            logger.info(f"[Playback Completed] Context {context_id}")

    async def _handle_incoming_audio(self, track: rtc.RemoteAudioTrack):
        stream = AudioStream(track)
        try:
            async for event in stream:
                await self.stt.send_audio(event.frame.data)
        except Exception as e:
            logger.error(f"[Audio Ingest Error] {e}")
        finally:
            await stream.aclose()

    async def run(self):
        logger.info(f"[RUNTIME] Starting RealtimeSession session={self.session_id}")
        self.audio_source = rtc.AudioSource(24000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("agent-audio", self.audio_source)

        @self.room.on("track_subscribed")
        def on_track_subscribed(t, publication, participant):
            if t.kind == rtc.TrackKind.KIND_AUDIO:
                task = asyncio.create_task(self._handle_incoming_audio(t))
                self.audio_tasks.add(task)
                task.add_done_callback(self.audio_tasks.discard)

        @self.room.on("disconnected")
        def on_disconnected():
            logger.info("[RUNTIME] Room disconnected")
            self.cancel_agent_tasks()
            for task in self.audio_tasks:
                task.cancel()

        try:
            await self.room.connect(settings.livekit_url, self.agent_token)
            logger.info(f"[RUNTIME] Connected to room {self.room_name}")
            await self.room.local_participant.publish_track(track)

            await self.stt.connect()
            await self.tts.connect()

            await self.room.local_participant.publish_data(
                json.dumps({"type": "mode_info", "mode": "hybrid", "phase": 3, "status": "conversational"}).encode()
            )

            greeting_text = "Hello! I'm Agent. You're connected in Hybrid mode. How can I help?"
            context_id = str(uuid.uuid4())
            self.state.current_context_id = context_id
            self.current_playback_task = asyncio.create_task(self._audio_playback_loop(context_id))
            await self.tts.send_text(greeting_text, context_id, continue_transcript=False)
            self.state.add_assistant_message(greeting_text)
            await self.room.local_participant.publish_data(
                json.dumps({"type": "transcription", "participant": "agent", "text": greeting_text}).encode()
            )

            while True:
                await asyncio.sleep(1)
                if len(self.room.remote_participants) == 0:
                    logger.info("[RUNTIME] Room empty, draining session")
                    break

        except asyncio.CancelledError:
            logger.info("[RUNTIME] Session cancelled")
        finally:
            self.cancel_agent_tasks()
            await self.stt.close()
            await self.tts.close()
            await self.room.disconnect()
            logger.info("[RUNTIME] Session closed")
