# CLAUDE.md — AgentOS Architecture Demo
## Three-Mode Voice Agent: LiveKit · Pipecat · Hybrid + Tool Calling

**Purpose:** Agent-optimized build instructions for a switchable demo that runs all three
architecture modes side-by-side. Used to evaluate and present each approach before
committing to production architecture.

**Switch mechanism:** `AGENT_MODE=livekit | pipecat | hybrid` in `.env`
**Tool calling:** Same three demo tools wired in all three modes
**Stack:** LiveKit 1.11 · Pipecat 1.1.0 · Deepgram Nova-3 · Cartesia Sonic · OpenAI gpt-4o-mini · Redis · Docker Compose

---

## ABSOLUTE RULES (read before writing any code)

1. **Never mix mode implementations.** LiveKit mode uses LiveKit Agents SDK only. Pipecat mode
   uses Pipecat only. Hybrid uses both with hard boundary. No cross-contamination.
2. **`AGENT_MODE` is read once at session start.** Never hot-switch mid-call.
3. **Tool implementations are shared.** One `services/agent/tools/` directory, imported by all
   three modes. Never duplicate tool logic per mode.
4. **Every phase has a binary done-check.** Do not start the next phase until every
   `[ ]` in the current phase is ticked.
5. **Never call `docker compose build --no-cache` unless a done-check explicitly requires it.**
   Layer cache is sacred during iterative development.
6. **All timing in done-checks is measured from end-of-speech to first audio in the browser.**
   Not from logs. Not from curl. From the browser.

---

## Final Repository Structure (target state after all phases)

```
agentOS-demo/
│
├── docker-compose.yml              # Orchestrates all 5 services
├── .env                            # AGENT_MODE + all provider keys
├── CLAUDE.md                       # This file
│
├── infra/
│   └── livekit.yaml                # LiveKit local dev config
│
└── services/
    ├── agent/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── config.py               # Pydantic settings — all config from env
    │   ├── main.py                 # FastAPI session gateway + mode router
    │   │
    │   ├── tools/                  # SHARED across all three modes
    │   │   ├── __init__.py
    │   │   ├── registry.py         # Tool definitions (OpenAI function schema)
    │   │   ├── handlers.py         # Tool execution logic (mock implementations)
    │   │   └── models.py           # Pydantic request/response models
    │   │
    │   ├── modes/
    │   │   ├── __init__.py
    │   │   ├── livekit_mode.py     # Phase 1: LiveKit Agents SDK pipeline
    │   │   ├── pipecat_mode.py     # Phase 2: Pipecat-only pipeline
    │   │   └── hybrid_mode.py      # Phase 3: LiveKit transport + Pipecat orchestration
    │   │
    │   └── pipeline/               # Shared Pipecat provider factories
    │       └── providers/
    │           ├── stt.py
    │           ├── tts.py
    │           └── llm.py
    │
    └── frontend/
        └── index.html              # Demo UI with mode indicator + tool call panel
```

---

## Environment File — complete reference

```env
# ── MODE SWITCH ──────────────────────────────────────────────────────
# Values: livekit | pipecat | hybrid
AGENT_MODE=hybrid

# ── LiveKit ───────────────────────────────────────────────────────────
LIVEKIT_URL=ws://livekit:7880
LIVEKIT_PUBLIC_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret

# ── STT ───────────────────────────────────────────────────────────────
STT_PROVIDER=deepgram
DEEPGRAM_API_KEY=your_key_here
AGENT_LANGUAGE=multi

# ── TTS ───────────────────────────────────────────────────────────────
TTS_PROVIDER=cartesia
CARTESIA_API_KEY=your_key_here
CARTESIA_VOICE_ID=your_voice_uuid_here

# ── LLM ───────────────────────────────────────────────────────────────
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=your_key_here

# ── Optional LLM alternates ───────────────────────────────────────────
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=your_key_here
# LLM_MODEL=claude-sonnet-4-20250514

# ── Infra ─────────────────────────────────────────────────────────────
REDIS_URL=redis://redis:6379
```

---

## Phase 0 — Foundation (do this first, always)

**Goal:** Repo skeleton, config, shared tool registry, health endpoint. No voice yet.

### 0.1 — Config

```python
# services/agent/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    agent_mode: str = "hybrid"          # livekit | pipecat | hybrid

    livekit_url: str = "ws://livekit:7880"
    livekit_public_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    stt_provider: str = "deepgram"
    tts_provider: str = "cartesia"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"

    deepgram_api_key: str = ""
    agent_language: str = "multi"

    cartesia_api_key: str = ""
    cartesia_voice_id: str = ""

    openai_api_key: str = ""
    anthropic_api_key: str = ""

    redis_url: str = "redis://redis:6379"

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
```

### 0.2 — Shared tool registry

```python
# services/agent/tools/registry.py
# These definitions are imported by all three modes.
# OpenAI function-calling schema format — compatible with Pipecat + LiveKit Agents + raw OpenAI.

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check if a time slot is available for an appointment",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format"
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM 24-hour format"
                    }
                },
                "required": ["date", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. Mumbai, Delhi, Bangalore"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_crm",
            "description": "Update a customer record in the CRM with new information",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "Field to update: name | phone | address | email"
                    },
                    "value": {
                        "type": "string",
                        "description": "New value for the field"
                    }
                },
                "required": ["field", "value"]
            }
        }
    }
]
```

```python
# services/agent/tools/handlers.py
# Mock implementations. Replace with real integrations in production.
import asyncio
import random
from datetime import datetime

async def check_availability(date: str, time: str) -> dict:
    await asyncio.sleep(0.3)  # simulate API latency
    available = random.choice([True, True, False])  # 67% available
    slots = ["09:00", "10:30", "14:00", "16:30"] if not available else []
    return {
        "available": available,
        "requested": f"{date} at {time}",
        "alternatives": slots if not available else [],
        "message": f"{'Available' if available else 'Slot taken. Alternatives: ' + ', '.join(slots)}"
    }

async def get_weather(city: str) -> dict:
    await asyncio.sleep(0.2)
    # Mock data — replace with OpenWeatherMap or similar
    weather_data = {
        "Mumbai":    {"temp": 32, "condition": "Humid and partly cloudy", "humidity": 78},
        "Delhi":     {"temp": 38, "condition": "Hot and hazy", "humidity": 45},
        "Bangalore": {"temp": 24, "condition": "Pleasant with light breeze", "humidity": 62},
    }
    data = weather_data.get(city, {"temp": 28, "condition": "Partly cloudy", "humidity": 60})
    return {
        "city": city,
        "temperature_c": data["temp"],
        "condition": data["condition"],
        "humidity_pct": data["humidity"],
        "summary": f"{city}: {data['temp']}°C, {data['condition']}"
    }

async def update_crm(field: str, value: str) -> dict:
    await asyncio.sleep(0.4)  # simulate CRM write latency
    return {
        "success": True,
        "field_updated": field,
        "new_value": value,
        "record_id": f"CRM-{random.randint(10000, 99999)}",
        "timestamp": datetime.utcnow().isoformat(),
        "message": f"Successfully updated {field} to '{value}'"
    }

# Dispatch table — used by all three modes
TOOL_HANDLERS = {
    "check_availability": check_availability,
    "get_weather": get_weather,
    "update_crm": update_crm,
}

async def execute_tool(name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"error": f"Unknown tool: {name}"}
    return await handler(**arguments)
```

### 0.3 — Session gateway (main.py)

```python
# services/agent/main.py
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import livekit.api as livekit_api

from config import settings

logger = logging.getLogger("uvicorn")
_sessions: dict[str, asyncio.Task] = {}


def _get_runner(session_id: str, room_name: str, agent_token: str):
    """Return the coroutine for the configured AGENT_MODE."""
    mode = settings.agent_mode.lower()
    if mode == "livekit":
        from modes.livekit_mode import run_session
    elif mode == "pipecat":
        from modes.pipecat_mode import run_session
    elif mode == "hybrid":
        from modes.hybrid_mode import run_session
    else:
        raise ValueError(f"Unknown AGENT_MODE: {mode!r}. Must be livekit | pipecat | hybrid")
    return run_session(session_id, room_name, agent_token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"AgentOS starting — mode={settings.agent_mode.upper()}")
    yield
    for task in list(_sessions.values()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("All sessions drained.")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class JoinRequest(BaseModel):
    user_identity: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": settings.agent_mode,
        "providers": {
            "stt": settings.stt_provider,
            "tts": settings.tts_provider,
            "llm": settings.llm_provider,
        },
        "active_sessions": len(_sessions),
    }


@app.get("/sessions")
async def list_sessions():
    return {"sessions": list(_sessions.keys()), "count": len(_sessions)}


@app.post("/session/join")
async def join_session(req: JoinRequest):
    session_id = str(uuid.uuid4())
    room_name = f"room-{session_id}"

    user_token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(req.user_identity)
        .with_grants(livekit_api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )
    agent_token = (
        livekit_api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"agent-{session_id}")
        .with_grants(livekit_api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )

    task = asyncio.create_task(
        _get_runner(session_id, room_name, agent_token),
        name=f"session-{session_id}",
    )
    _sessions[session_id] = task
    task.add_done_callback(lambda t: _sessions.pop(session_id, None))

    logger.info(f"session.start mode={settings.agent_mode} id={session_id}")
    return {
        "session_id": session_id,
        "room_name": room_name,
        "token": user_token,
        "livekit_url": settings.livekit_public_url,
        "mode": settings.agent_mode,
    }


@app.delete("/session/{session_id}")
async def end_session(session_id: str):
    task = _sessions.get(session_id)
    if not task:
        return {"error": "not found"}
    task.cancel()
    return {"cancelled": session_id}
```

### 0.4 — requirements.txt

```txt
pipecat-ai[silero,deepgram,cartesia,openai,anthropic,livekit]>=1.1.0
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
livekit>=0.17.0
livekit-api>=0.7.0
livekit-agents>=0.12.0
livekit-plugins-openai>=0.10.0
livekit-plugins-deepgram>=0.6.0
livekit-plugins-cartesia>=0.4.0
livekit-plugins-silero>=0.6.0
python-dotenv>=1.0.0
pydantic-settings>=2.0.0
redis[asyncio]>=5.0.0
httpx>=0.27.0
```

### 0.5 — Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libsndfile1 ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]
```

### Phase 0 done-checks

```
[ ] docker compose build succeeds with no errors
[ ] curl http://localhost:8080/health returns {"status":"ok","mode":"hybrid",...}
[ ] Changing AGENT_MODE=livekit and restarting returns {"mode":"livekit"}
[ ] Changing AGENT_MODE=pipecat and restarting returns {"mode":"pipecat"}
[ ] curl http://localhost:8080/sessions returns {"sessions":[],"count":0}
```

---

## Phase 1 — LiveKit Mode (AGENT_MODE=livekit)

**Goal:** Full voice pipeline using LiveKit Agents SDK only. No Pipecat.
**Characteristics:** Room-centric, event-driven, minimal control over frame internals.
**Best for demonstrating:** Simplicity, quick setup, LiveKit-native multi-participant.

```python
# services/agent/modes/livekit_mode.py
import asyncio
import json
import logging
from typing import Annotated

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.multimodal import MultimodalAgent
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import cartesia, deepgram, openai, silero

from config import settings
from tools.registry import TOOL_DEFINITIONS
from tools.handlers import execute_tool

logger = logging.getLogger("uvicorn")

SYSTEM_PROMPT = """You are Aria, a helpful voice assistant for Indian enterprise customers.
Speak in natural conversational Indian English. Keep responses to 1-2 short sentences.
Do not use bullet points, markdown, or lists in your spoken responses.
You have access to three tools: check_availability, get_weather, and update_crm.
Use them when the user asks about appointments, weather, or updating their details."""


async def run_session(session_id: str, room_name: str, agent_token: str):
    """
    LiveKit Agents mode.
    Uses LiveKit VoiceAssistant — room-centric, event-driven.
    Tool calling via livekit.agents.llm.FunctionContext.
    """
    logger.info(f"[LIVEKIT MODE] session={session_id} room={room_name}")

    # Build LiveKit FunctionContext from shared tool definitions
    fnc_ctx = llm.FunctionContext()

    @fnc_ctx.ai_callable(
        description="Check if a time slot is available for an appointment"
    )
    async def check_availability(
        date: Annotated[str, llm.TypeInfo(description="Date YYYY-MM-DD")],
        time: Annotated[str, llm.TypeInfo(description="Time HH:MM 24h")],
    ):
        result = await execute_tool("check_availability", {"date": date, "time": time})
        return result["message"]

    @fnc_ctx.ai_callable(description="Get current weather for a city")
    async def get_weather(
        city: Annotated[str, llm.TypeInfo(description="City name e.g. Mumbai")]
    ):
        result = await execute_tool("get_weather", {"city": city})
        return result["summary"]

    @fnc_ctx.ai_callable(description="Update a customer record in the CRM")
    async def update_crm(
        field: Annotated[str, llm.TypeInfo(description="Field: name|phone|address|email")],
        value: Annotated[str, llm.TypeInfo(description="New value")],
    ):
        result = await execute_tool("update_crm", {"field": field, "value": value})
        return result["message"]

    # Connect to the LiveKit room
    room = rtc.Room()
    await room.connect(settings.livekit_url, agent_token)
    logger.info(f"[LIVEKIT MODE] agent joined room={room_name}")

    # Build the assistant
    assistant = VoiceAssistant(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            api_key=settings.deepgram_api_key,
            language=settings.agent_language,
            model="nova-2",
        ),
        llm=openai.LLM(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
        ),
        tts=cartesia.TTS(
            api_key=settings.cartesia_api_key,
            voice=settings.cartesia_voice_id,
        ),
        fnc_ctx=fnc_ctx,
        chat_ctx=llm.ChatContext().append(
            role="system",
            text=SYSTEM_PROMPT,
        ),
        allow_interruptions=True,
        interrupt_speech_duration=0.5,
        interrupt_min_words=0,
    )

    assistant.start(room)

    # Broadcast mode info via data channel so frontend can display it
    await asyncio.sleep(0.5)
    await room.local_participant.publish_data(
        json.dumps({"type": "mode_info", "mode": "livekit", "session_id": session_id}).encode()
    )

    # Greet the user
    await assistant.say("Namaste! I'm Aria. You're connected in LiveKit mode. How can I help you?",
                        allow_interruptions=True)

    # Keep running until room is empty
    try:
        while True:
            await asyncio.sleep(1)
            if len(room.remote_participants) == 0:
                logger.info(f"[LIVEKIT MODE] room empty, ending session={session_id}")
                break
    except asyncio.CancelledError:
        pass
    finally:
        await room.disconnect()
        logger.info(f"[LIVEKIT MODE] session done={session_id}")
```

### Phase 1 done-checks

```
[ ] Set AGENT_MODE=livekit in .env, docker compose restart agent
[ ] curl /health shows mode=livekit
[ ] Browser connects, orb goes live, greeting plays in under 2 seconds
[ ] Say "What's the weather in Mumbai?" — agent calls get_weather tool and speaks result
[ ] Say "Check if tomorrow 3pm is available" — agent calls check_availability and speaks result
[ ] Say "Update my phone to 9876543210" — agent calls update_crm and speaks confirmation
[ ] Interrupt agent mid-sentence — audio stops within 200ms, new turn begins
[ ] Disconnect browser — session cleans up (check /sessions returns count 0)
[ ] docker compose logs agent shows [LIVEKIT MODE] prefix on all log lines
```

---

## Phase 2 — Pipecat Mode (AGENT_MODE=pipecat)

**Goal:** Full voice pipeline using Pipecat only. LiveKit is transport only — Pipecat owns all orchestration.
**Characteristics:** Explicit frame pipeline, full processor control, observable at every stage.
**Best for demonstrating:** Pipeline visibility, custom processor injection, PII redaction slot.

```python
# services/agent/modes/pipecat_mode.py
import asyncio
import json
import logging

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    TextFrame,
    TranscriptionFrame,
    TTSTextFrame,
)
from pipecat.observers.base_observer import BaseObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.transports.services.livekit import LiveKitParams, LiveKitTransport

from config import settings
from pipeline.providers.stt import create_stt_service
from pipeline.providers.tts import create_tts_service
from pipeline.providers.llm import create_llm_service
from tools.registry import TOOL_DEFINITIONS
from tools.handlers import execute_tool

logger = logging.getLogger("uvicorn")

SYSTEM_PROMPT = """You are Aria, a helpful voice assistant for Indian enterprise customers.
Speak in natural conversational Indian English. Keep responses to 1-2 short sentences.
Do not use bullet points, markdown, or lists.
You have access to tools: check_availability, get_weather, update_crm.
Use them when relevant. After a tool call, speak the result naturally."""


class TranscriptBroadcaster(BaseObserver):
    """Watches frames and relays transcripts to the frontend via LiveKit data channel."""

    def __init__(self, transport: LiveKitTransport, session_id: str):
        self._transport = transport
        self._session_id = session_id
        self._agent_buffer: list[str] = []

    async def on_push_frame(self, src, dst, frame, direction, timestamp):
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            payload = json.dumps({
                "type": "transcription",
                "participant": "user",
                "text": frame.text,
                "session_id": self._session_id,
            }).encode()
            await self._transport.send_message(payload)

        if isinstance(frame, TTSTextFrame) and frame.text.strip():
            self._agent_buffer.append(frame.text)

        if isinstance(frame, LLMFullResponseEndFrame):
            full = " ".join(self._agent_buffer).strip()
            if full:
                payload = json.dumps({
                    "type": "transcription",
                    "participant": "agent",
                    "text": full,
                    "session_id": self._session_id,
                }).encode()
                await self._transport.send_message(payload)
            self._agent_buffer = []


async def run_session(session_id: str, room_name: str, agent_token: str):
    """
    Pipecat-only mode.
    LiveKit is transport only. Pipecat owns the entire cognitive pipeline.
    Tool calling via Pipecat register_function + shared handlers.
    """
    logger.info(f"[PIPECAT MODE] session={session_id} room={room_name}")

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
                params=VADParams(stop_secs=0.5, min_volume=0.4, confidence=0.7)
            ),
            vad_audio_passthrough=True,
        ),
    )

    stt = create_stt_service()
    tts = create_tts_service()
    llm = create_llm_service()

    # Register tools with the LLM service
    llm.register_function("check_availability",
        lambda **kwargs: execute_tool("check_availability", kwargs))
    llm.register_function("get_weather",
        lambda **kwargs: execute_tool("get_weather", kwargs))
    llm.register_function("update_crm",
        lambda **kwargs: execute_tool("update_crm", kwargs))

    context = OpenAILLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=TOOL_DEFINITIONS,
    )
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True, enable_metrics=True),
    )

    broadcaster = TranscriptBroadcaster(transport, session_id)
    task.add_observer(broadcaster)

    @transport.event_handler("on_first_participant_joined")
    async def on_joined(transport, participant):
        logger.info(f"[PIPECAT MODE] participant joined session={session_id}")
        transport.capture_participant_audio(participant)
        # Broadcast mode info
        await transport.send_message(json.dumps({
            "type": "mode_info",
            "mode": "pipecat",
            "session_id": session_id
        }).encode())
        await task.queue_frames([
            TextFrame("Namaste! I'm Aria. You're connected in Pipecat mode. How can I help?")
        ])

    @transport.event_handler("on_participant_left")
    async def on_left(transport, participant, reason):
        logger.info(f"[PIPECAT MODE] participant left session={session_id}")
        await task.cancel()

    runner = PipelineRunner()
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        logger.info(f"[PIPECAT MODE] session cancelled={session_id}")
    finally:
        logger.info(f"[PIPECAT MODE] session done={session_id}")
```

### Phase 2 done-checks

```
[ ] Set AGENT_MODE=pipecat in .env, docker compose restart agent
[ ] curl /health shows mode=pipecat
[ ] Browser connects, greeting plays — confirms "Pipecat mode" verbally
[ ] Say "What's the weather in Delhi?" — tool executes, result spoken naturally
[ ] Say "Is Friday 10am available?" — check_availability executes and responds
[ ] Say "Update my address to 123 MG Road Bangalore" — update_crm executes
[ ] docker compose logs agent shows [PIPECAT MODE] prefix
[ ] Interrupt mid-sentence — audio stops, new turn begins correctly
[ ] Browser DevTools console shows mode_info data message with "mode":"pipecat"
```

---

## Phase 3 — Hybrid Mode (AGENT_MODE=hybrid)

**Goal:** LiveKit owns media transport. Pipecat owns all cognitive orchestration.
**Characteristics:** Best of both. PII slot available. Speculative TTS ready. Hard ownership boundary.
**Best for demonstrating:** Production-grade architecture. Frame visibility + media reliability.

```python
# services/agent/modes/hybrid_mode.py
import asyncio
import json
import logging
import re

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    TextFrame,
    TranscriptionFrame,
    TTSTextFrame,
)
from pipecat.observers.base_observer import BaseObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.transports.services.livekit import LiveKitParams, LiveKitTransport

from config import settings
from pipeline.providers.stt import create_stt_service
from pipeline.providers.tts import create_tts_service
from pipeline.providers.llm import create_llm_service
from tools.registry import TOOL_DEFINITIONS
from tools.handlers import execute_tool

logger = logging.getLogger("uvicorn")

SYSTEM_PROMPT = """You are Aria, a helpful voice assistant for Indian enterprise customers.
Speak in natural conversational Indian English. Keep responses to 1-2 short sentences.
Do not use bullet points, markdown, or lists.
You have tools: check_availability, get_weather, update_crm. Use them when the user asks.
Speak results naturally — never say "the tool returned" or "the function said"."""


# ── PII Scrubber ────────────────────────────────────────────────────────────
# Sits between STT and LLM. Scrubs before any cloud service sees the text.
# Expand patterns for production (credit cards, Aadhaar, PAN, UPI IDs, etc.)

class PIIScrubberProcessor(FrameProcessor):
    PATTERNS = [
        (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), '[CARD_REDACTED]'),
        (re.compile(r'\b\d{12}\b'), '[AADHAAR_REDACTED]'),
        (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'), '[PAN_REDACTED]'),
        (re.compile(r'\b\d{10}\b'), '[PHONE_REDACTED]'),
    ]

    async def process_frame(self, frame: Frame, direction):
        if isinstance(frame, TranscriptionFrame):
            scrubbed = frame.text
            for pattern, replacement in self.PATTERNS:
                scrubbed = pattern.sub(replacement, scrubbed)
            if scrubbed != frame.text:
                logger.info(f"[HYBRID MODE] PII scrubbed in transcript")
            frame = TranscriptionFrame(
                text=scrubbed,
                user_id=frame.user_id,
                timestamp=frame.timestamp,
                language=frame.language,
            )
        await self.push_frame(frame, direction)


# ── Transcript broadcaster ──────────────────────────────────────────────────

class TranscriptBroadcaster(BaseObserver):
    def __init__(self, transport: LiveKitTransport, session_id: str):
        self._transport = transport
        self._session_id = session_id
        self._agent_buffer: list[str] = []

    async def on_push_frame(self, src, dst, frame, direction, timestamp):
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            await self._transport.send_message(json.dumps({
                "type": "transcription",
                "participant": "user",
                "text": frame.text,
                "session_id": self._session_id,
            }).encode())

        if isinstance(frame, TTSTextFrame) and frame.text.strip():
            self._agent_buffer.append(frame.text)

        if isinstance(frame, LLMFullResponseEndFrame):
            full = " ".join(self._agent_buffer).strip()
            if full:
                await self._transport.send_message(json.dumps({
                    "type": "transcription",
                    "participant": "agent",
                    "text": full,
                    "session_id": self._session_id,
                }).encode())
            self._agent_buffer = []


# ── Session runner ──────────────────────────────────────────────────────────

async def run_session(session_id: str, room_name: str, agent_token: str):
    """
    Hybrid mode.
    LiveKit: media transport, WebRTC, audio routing, room lifecycle.
    Pipecat: all cognitive orchestration, PII scrubbing, tool execution.
    Hard boundary: LiveKitTransport is the only Pipecat component that touches LiveKit.
    """
    logger.info(f"[HYBRID MODE] session={session_id} room={room_name}")

    # ── LiveKit owns this ────────────────────────────────────────────────────
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
                params=VADParams(stop_secs=0.5, min_volume=0.4, confidence=0.7)
            ),
            vad_audio_passthrough=True,
        ),
    )

    # ── Pipecat owns everything below ────────────────────────────────────────
    stt = create_stt_service()
    pii = PIIScrubberProcessor()       # ← impossible in LiveKit-only mode
    tts = create_tts_service()
    llm = create_llm_service()

    llm.register_function("check_availability",
        lambda **kwargs: execute_tool("check_availability", kwargs))
    llm.register_function("get_weather",
        lambda **kwargs: execute_tool("get_weather", kwargs))
    llm.register_function("update_crm",
        lambda **kwargs: execute_tool("update_crm", kwargs))

    context = OpenAILLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=TOOL_DEFINITIONS,
    )
    context_aggregator = llm.create_context_aggregator(context)

    # Explicit pipeline — every stage visible, every stage interceptable
    pipeline = Pipeline([
        transport.input(),              # LiveKit → PCM frames
        stt,                            # PCM → TranscriptionFrame
        pii,                            # Scrub PII before LLM sees text
        context_aggregator.user(),      # Append user turn to context
        llm,                            # Stream tokens + tool calls
        tts,                            # Tokens → audio frames
        transport.output(),             # Audio frames → LiveKit
        context_aggregator.assistant(), # Record assistant turn
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True, enable_metrics=True),
    )

    task.add_observer(TranscriptBroadcaster(transport, session_id))

    @transport.event_handler("on_first_participant_joined")
    async def on_joined(transport, participant):
        logger.info(f"[HYBRID MODE] participant joined session={session_id}")
        transport.capture_participant_audio(participant)
        await transport.send_message(json.dumps({
            "type": "mode_info",
            "mode": "hybrid",
            "features": ["PII scrubbing", "explicit pipeline", "tool calling", "interruptions"],
            "session_id": session_id,
        }).encode())
        await task.queue_frames([
            TextFrame("Namaste! I'm Aria. You're in Hybrid mode — LiveKit media, Pipecat brain. How can I help?")
        ])

    @transport.event_handler("on_participant_left")
    async def on_left(transport, participant, reason):
        logger.info(f"[HYBRID MODE] participant left session={session_id}")
        await task.cancel()

    runner = PipelineRunner()
    try:
        await runner.run(task)
    except asyncio.CancelledError:
        logger.info(f"[HYBRID MODE] session cancelled={session_id}")
    finally:
        logger.info(f"[HYBRID MODE] session done={session_id}")
```

### Phase 3 done-checks

```
[ ] Set AGENT_MODE=hybrid in .env, docker compose restart agent
[ ] curl /health shows mode=hybrid
[ ] Browser connects, greeting plays — confirms "Hybrid mode" verbally
[ ] All three tools work: weather, availability, CRM update
[ ] Speak "my card number is 4111111111111111" — logs show [HYBRID MODE] PII scrubbed
[ ] The PAN/Aadhaar patterns also scrub — test with "my Aadhaar is 123456789012"
[ ] mode_info data message shows features array including "PII scrubbing"
[ ] docker compose logs show [HYBRID MODE] prefix consistently
[ ] Interruption works correctly — audio stops, new turn begins
```

---

## Phase 4 — Tool Calling Validation (all three modes)

**Goal:** Confirm all three tools work in all three modes with identical results.
Run this phase after Phases 1, 2, and 3 are individually complete.

### Test script — run against each mode

```bash
# Set mode, restart, then run these voice prompts and verify spoken responses:

# Tool 1: get_weather
# Say: "What's the weather like in Bangalore right now?"
# Expected: Agent speaks temperature + condition for Bangalore

# Tool 2: check_availability — available slot
# Say: "Can you check if tomorrow at 2pm is available for a meeting?"
# Expected: Agent confirms availability or offers alternatives

# Tool 3: update_crm
# Say: "Please update my email address to arjun at example dot com"
# Expected: Agent confirms "Successfully updated email to arjun@example.com"

# Tool chaining test (hybrid and pipecat modes)
# Say: "Check if Monday 9am is free, and if it is, update my name to Arjun Sharma"
# Expected: Agent calls check_availability, then conditionally calls update_crm
```

### Phase 4 done-checks

```
[ ] All three tools respond correctly in AGENT_MODE=livekit
[ ] All three tools respond correctly in AGENT_MODE=pipecat
[ ] All three tools respond correctly in AGENT_MODE=hybrid
[ ] Tool latency is non-blocking — agent speaks "Let me check that..." while tool runs
[ ] Failed/slow tool (simulate by adding 2s sleep to a handler) — agent handles gracefully
[ ] Tool results are spoken naturally, not as raw JSON
```

---

## Phase 5 — Demo UI with Mode Switcher

**Goal:** Frontend that shows which mode is active, displays live transcripts,
shows tool calls firing in real time, and lets a presenter switch modes
between demonstrations.

Replace `services/frontend/index.html` entirely:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AgentOS Architecture Demo</title>
  <script src="https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f0f0f;
      color: #e0e0e0;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 32px 16px;
    }

    /* ── Header ── */
    .header { text-align: center; margin-bottom: 32px; }
    .header h1 { font-size: 22px; font-weight: 600; color: #fff; margin-bottom: 4px; }
    .header p { font-size: 13px; color: #666; }

    /* ── Mode selector ── */
    .mode-selector {
      display: flex; gap: 8px; margin-bottom: 24px;
    }
    .mode-btn {
      padding: 8px 20px;
      border-radius: 6px;
      border: 1px solid #333;
      background: #1a1a1a;
      color: #888;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .mode-btn:hover { border-color: #555; color: #ccc; }
    .mode-btn.active-livekit { background: #0d2d4a; border-color: #1d7fc4; color: #5bb3f5; }
    .mode-btn.active-pipecat { background: #2a1a0a; border-color: #c47a1d; color: #f5a855; }
    .mode-btn.active-hybrid  { background: #0d2d1a; border-color: #1dc47a; color: #55f5a8; }

    /* ── Mode badge ── */
    .mode-badge {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 12px; border-radius: 20px;
      font-size: 12px; font-weight: 600; letter-spacing: 0.5px;
      margin-bottom: 20px;
    }
    .badge-livekit { background: #0d2d4a; color: #5bb3f5; border: 1px solid #1d7fc4; }
    .badge-pipecat { background: #2a1a0a; color: #f5a855; border: 1px solid #c47a1d; }
    .badge-hybrid  { background: #0d2d1a; color: #55f5a8; border: 1px solid #1dc47a; }
    .badge-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

    /* ── Orb ── */
    .orb-container { display: flex; justify-content: center; margin-bottom: 20px; }
    .orb {
      width: 80px; height: 80px; border-radius: 50%;
      background: #222;
      border: 2px solid #333;
      transition: all 0.3s;
      position: relative;
    }
    .orb.connected { border-color: #1d7fc4; box-shadow: 0 0 20px rgba(29,127,196,0.3); }
    .orb.speaking  {
      animation: pulse 0.8s ease-in-out infinite;
      border-color: #55f5a8;
      box-shadow: 0 0 30px rgba(85,245,168,0.4);
    }
    @keyframes pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.08); }
    }

    /* ── Status ── */
    .status { font-size: 13px; color: #666; margin-bottom: 20px; text-align: center; }

    /* ── Connect button ── */
    .connect-btn {
      padding: 10px 32px; border-radius: 8px;
      border: none; font-size: 14px; font-weight: 500;
      cursor: pointer; transition: all 0.15s; margin-bottom: 24px;
    }
    .connect-btn.idle       { background: #1d7fc4; color: #fff; }
    .connect-btn.idle:hover { background: #2490d8; }
    .connect-btn.live       { background: #c41d1d; color: #fff; }
    .connect-btn.live:hover { background: #d82424; }

    /* ── Layout ── */
    .panels { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; width: 100%; max-width: 860px; }
    @media (max-width: 600px) { .panels { grid-template-columns: 1fr; } }

    /* ── Panel ── */
    .panel {
      background: #161616;
      border: 1px solid #2a2a2a;
      border-radius: 10px;
      overflow: hidden;
    }
    .panel-header {
      padding: 10px 14px;
      border-bottom: 1px solid #2a2a2a;
      font-size: 11px;
      font-weight: 600;
      color: #555;
      letter-spacing: 0.8px;
      text-transform: uppercase;
    }
    .panel-body { padding: 12px; min-height: 180px; max-height: 240px; overflow-y: auto; }

    /* ── Transcript entries ── */
    .turn { margin-bottom: 10px; }
    .turn-label { font-size: 10px; font-weight: 600; letter-spacing: 0.5px; margin-bottom: 2px; }
    .turn-label.user  { color: #888; }
    .turn-label.agent { color: #55f5a8; }
    .turn-text { font-size: 13px; line-height: 1.5; color: #ccc; }

    /* ── Tool events ── */
    .tool-event {
      padding: 8px 10px;
      border-radius: 6px;
      background: #1a1a2e;
      border: 1px solid #2a2a4a;
      margin-bottom: 8px;
      font-size: 12px;
    }
    .tool-name { color: #7c88f5; font-weight: 600; margin-bottom: 2px; }
    .tool-args { color: #666; font-size: 11px; }
    .tool-result { color: #55f5a8; font-size: 11px; margin-top: 4px; }

    /* ── Architecture note ── */
    .arch-note {
      max-width: 860px; width: 100%;
      padding: 12px 16px;
      background: #161616;
      border: 1px solid #2a2a2a;
      border-radius: 10px;
      font-size: 12px;
      color: #555;
      margin-top: 16px;
      line-height: 1.6;
    }
    .arch-note strong { color: #888; }
  </style>
</head>
<body>

<div class="header">
  <h1>AgentOS Architecture Demo</h1>
  <p>LiveKit · Pipecat · Hybrid — switch modes between demonstrations</p>
</div>

<!-- Mode selector -->
<div class="mode-selector">
  <button class="mode-btn" onclick="setMode('livekit')" id="btn-livekit">LiveKit</button>
  <button class="mode-btn" onclick="setMode('pipecat')" id="btn-pipecat">Pipecat</button>
  <button class="mode-btn" onclick="setMode('hybrid')"  id="btn-hybrid">Hybrid</button>
</div>

<!-- Active mode badge -->
<div class="mode-badge" id="mode-badge">
  <div class="badge-dot"></div>
  <span id="mode-label">hybrid</span>
</div>

<!-- Orb -->
<div class="orb-container">
  <div class="orb" id="orb"></div>
</div>

<div class="status" id="status">Select a mode and click Connect</div>

<button class="connect-btn idle" id="btn-connect" onclick="toggleConnection()">
  Connect
</button>

<!-- Transcript + Tools panels -->
<div class="panels">
  <div class="panel">
    <div class="panel-header">Live Transcript</div>
    <div class="panel-body" id="transcript">
      <div style="color:#444;font-size:12px;">Conversation will appear here...</div>
    </div>
  </div>
  <div class="panel">
    <div class="panel-header">Tool Calls</div>
    <div class="panel-body" id="tools">
      <div style="color:#444;font-size:12px;">Tool executions will appear here...</div>
    </div>
  </div>
</div>

<!-- Architecture note — updates per mode -->
<div class="arch-note" id="arch-note">
  Select a mode to see its architecture description.
</div>

<audio id="agent-audio" autoplay></audio>

<script>
const ARCH_NOTES = {
  livekit: `<strong>LiveKit mode:</strong> Room-centric, event-driven. LiveKit Agents SDK owns the entire pipeline — STT, LLM, TTS are all wired through the AgentServer. Fast to set up. Limited pipeline visibility. Cannot insert custom processors between STT and LLM.`,
  pipecat: `<strong>Pipecat mode:</strong> Explicit frame pipeline. Every processor is visible and interceptable. LiveKit is transport only — Pipecat owns all orchestration. PII scrubbing, custom processors, and speculative TTS are all possible here.`,
  hybrid:  `<strong>Hybrid mode:</strong> LiveKit owns media (WebRTC, RTP, SIP, TURN). Pipecat owns cognition (pipeline, PII scrubber, tools, interruptions, context). Hard ownership boundary between the two. Production-recommended architecture.`,
};

let currentMode = 'hybrid';
let room = null;
let connected = false;

function setMode(mode) {
  if (connected) {
    setStatus('Disconnect first before switching modes.');
    return;
  }
  currentMode = mode;

  // Update buttons
  ['livekit','pipecat','hybrid'].forEach(m => {
    const btn = document.getElementById('btn-' + m);
    btn.className = 'mode-btn' + (m === mode ? ` active-${m}` : '');
  });

  // Update badge
  const badge = document.getElementById('mode-badge');
  badge.className = `mode-badge badge-${mode}`;
  document.getElementById('mode-label').textContent = mode.toUpperCase();

  // Update arch note
  document.getElementById('arch-note').innerHTML = ARCH_NOTES[mode];
}

setMode('hybrid');

function setStatus(msg) {
  document.getElementById('status').textContent = msg;
}

function addTranscript(text, participant) {
  const panel = document.getElementById('transcript');
  const first = panel.querySelector('[style]');
  if (first) first.remove();

  const div = document.createElement('div');
  div.className = 'turn';
  div.innerHTML = `
    <div class="turn-label ${participant}">${participant.toUpperCase()}</div>
    <div class="turn-text">${text}</div>
  `;
  panel.appendChild(div);
  panel.scrollTop = panel.scrollHeight;
}

function addToolEvent(name, args, result) {
  const panel = document.getElementById('tools');
  const first = panel.querySelector('[style]');
  if (first) first.remove();

  const div = document.createElement('div');
  div.className = 'tool-event';
  div.innerHTML = `
    <div class="tool-name">⚡ ${name}()</div>
    <div class="tool-args">${JSON.stringify(args)}</div>
    ${result ? `<div class="tool-result">→ ${result}</div>` : ''}
  `;
  panel.appendChild(div);
  panel.scrollTop = panel.scrollHeight;
}

async function toggleConnection() {
  if (connected) {
    await disconnect();
  } else {
    await connect();
  }
}

async function connect() {
  setStatus('Connecting...');
  try {
    const res = await fetch('http://localhost:8080/session/join', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_identity: 'demo-user-' + Date.now() }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    // Verify server mode matches selected mode
    if (data.mode !== currentMode) {
      setStatus(`⚠ Server is in ${data.mode.toUpperCase()} mode. Change AGENT_MODE in .env to ${currentMode}.`);
      return;
    }

    room = new LivekitClient.Room({
      audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });

    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === 'audio') {
        const audio = document.getElementById('agent-audio');
        track.attach(audio);
        document.getElementById('orb').className = 'orb connected speaking';
      }
    });

    room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
      if (track.kind === 'audio') {
        document.getElementById('orb').className = 'orb connected';
      }
    });

    room.on(LivekitClient.RoomEvent.DataReceived, (payload) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));

        if (msg.type === 'transcription') {
          addTranscript(msg.text, msg.participant);
        }

        if (msg.type === 'tool_call') {
          addToolEvent(msg.tool, msg.args, null);
        }

        if (msg.type === 'tool_result') {
          addToolEvent(msg.tool, msg.args, msg.result);
        }

        if (msg.type === 'mode_info') {
          setStatus(`Connected — ${msg.mode.toUpperCase()} mode active`);
        }
      } catch (e) {}
    });

    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      connected = false;
      document.getElementById('orb').className = 'orb';
      document.getElementById('btn-connect').className = 'connect-btn idle';
      document.getElementById('btn-connect').textContent = 'Connect';
      setStatus('Disconnected');
    });

    await room.connect(data.livekit_url, data.token);
    await room.localParticipant.setMicrophoneEnabled(true);

    connected = true;
    document.getElementById('orb').className = 'orb connected';
    document.getElementById('btn-connect').className = 'connect-btn live';
    document.getElementById('btn-connect').textContent = 'Disconnect';
    setStatus(`Connected — ${currentMode.toUpperCase()} mode`);

  } catch (e) {
    setStatus('Connection failed: ' + e.message);
    console.error(e);
  }
}

async function disconnect() {
  if (room) {
    await room.disconnect();
    room = null;
  }
  connected = false;
  document.getElementById('orb').className = 'orb';
  document.getElementById('btn-connect').className = 'connect-btn idle';
  document.getElementById('btn-connect').textContent = 'Connect';
  setStatus('Disconnected — switch mode or reconnect');
}
</script>
</body>
</html>
```

### Phase 5 done-checks

```
[ ] http://localhost:3000 loads with mode selector showing LiveKit / Pipecat / Hybrid buttons
[ ] Clicking a mode button updates the badge colour and architecture note text
[ ] Connecting in hybrid mode shows green badge and correct arch note
[ ] Transcripts appear in real time in the Transcript panel
[ ] Tool calls appear in the Tool Calls panel with name + args + result
[ ] Switching mode while connected shows warning message
[ ] Disconnect then switch mode — next connect uses new mode
[ ] Mode mismatch between frontend selection and server AGENT_MODE shows warning
```

---

## Full Build Sequence (run phases in order)

```bash
# One-time setup
cp .env.example .env
# Fill in DEEPGRAM_API_KEY, CARTESIA_API_KEY, CARTESIA_VOICE_ID, OPENAI_API_KEY

# Phase 0 — Foundation
docker compose build
docker compose up -d
curl http://localhost:8080/health    # must return ok

# Phase 1 — LiveKit mode
# Edit .env: AGENT_MODE=livekit
docker compose restart agent
# Run Phase 1 done-checks

# Phase 2 — Pipecat mode
# Edit .env: AGENT_MODE=pipecat
docker compose restart agent
# Run Phase 2 done-checks

# Phase 3 — Hybrid mode
# Edit .env: AGENT_MODE=hybrid
docker compose restart agent
# Run Phase 3 done-checks

# Phase 4 — Tool validation (no restart needed)
# Run all three tool tests in each mode

# Phase 5 — Demo UI
# Replace index.html, nginx picks up immediately — no restart
# Open http://localhost:3000
# Run Phase 5 done-checks
```

---

## Mode Comparison Reference (for demo presenter)

| Capability | LiveKit | Pipecat | Hybrid |
|---|---|---|---|
| Media reliability (WebRTC, SIP, RTP) | ✅ Best | ⚠ Basic | ✅ Best |
| Pipeline visibility | ❌ Abstracted | ✅ Full | ✅ Full |
| PII scrubbing between STT and LLM | ❌ Not possible | ✅ | ✅ |
| Tool calling | ✅ FunctionContext | ✅ register_function | ✅ register_function |
| Custom processor injection | ❌ | ✅ | ✅ |
| Interruption handling | ✅ Built-in | ✅ Built-in | ✅ Built-in |
| Exotel/SIP telephony (production) | ✅ Native | ❌ Need custom | ✅ Via LiveKit |
| Framework lock-in risk | High | Medium | Low |
| Operational complexity | Low | Medium | Medium-High |
| Path to Custom Runtime | Rewrite | Swap processors | Swap processors |

---

## Troubleshooting

**Mode not switching after restart**
```bash
docker compose logs agent | head -5
# Should show: AgentOS starting — mode=LIVEKIT/PIPECAT/HYBRID
# If still old mode: docker compose down && docker compose up -d
```

**Tool not executing (no tool event in UI)**
```bash
docker compose logs agent | grep "tool\|function"
# Check that OPENAI_API_KEY is valid — tool calling requires a real key
# Ollama does NOT support tool calling in standard mode
# For Ollama: switch LLM_PROVIDER=openai for Phase 4
```

**PII scrubber not visible in hybrid mode**
```bash
# Speak: "my card is 4111111111111111"
docker compose logs agent | grep "PII scrubbed"
# Should appear. If not, confirm AGENT_MODE=hybrid
```

**Mode mismatch warning in browser**
```
Server is in HYBRID mode. Change AGENT_MODE in .env to livekit.
```
The frontend selection and the server's `.env` must match.
Change `.env → AGENT_MODE`, then `docker compose restart agent`.

---

*Document version: 1.0 — Avesta AgentOS three-mode demo*
*Compatible with: LiveKit 1.11 · Pipecat 1.1.0 · livekit-agents 0.12*