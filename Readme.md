# VOICE POC 

**POC Scope:** Browser WebRTC voice agent, India language profile  
**Stack:** LiveKit · Pipecat 1.1.0 · Deepgram Nova-3 · Cartesia Sonic · OpenAI (gpt-4o-mini) · Redis  
**Infra:** Docker Compose (local dev)

---

## Table of Contents

1. [What We're Building](#1-what-youre-building)
2. [Repository Structure](#2-repository-structure)
3. [Prerequisites](#3-prerequisites)
4. [API Keys You Need](#4-api-keys-you-need)
5. [Step-by-Step Setup](#5-step-by-step-setup)
6. [File-by-File Reference](#6-file-by-file-reference)
7. [Pipeline Working](#7-how-the-pipeline-actually-works)
8. [Provider Swapping](#8-provider-swapping-guide)
9. [V&V](#9-testing--validation)
10. [Latency Benchmarking](#10-latency-benchmarking)
11. [Failures & Fixes](#11-common-failures--fixes)
12. [POC Extended](#12-extending-the-poc)
13. [Production Readiness check](#13-production-readiness-checklist)
14. [Architecture Decision Log](#14-architecture-decision-log)
15. [System Architecture](#15-system-architecture)

---

## 1. What You're Building

A **single-turn real-time voice agent** running entirely on your laptop inside Docker. A user opens a browser, clicks Connect, speaks (English or Hinglish), and receives a spoken AI response within ~300ms of finishing their sentence.

### What this POC proves

- WebRTC transport over LiveKit works locally with zero cloud dependency
- Pipecat's pipeline architecture cleanly separates transport, STT, LLM, and TTS
- Every intelligence provider (STT / LLM / TTS) is swappable via a single env var with no code changes
- Silero VAD handles barge-in interruptions correctly without energy-threshold hacks
- The session isolation model (one asyncio.Task per call) is crash-safe

### What this POC does NOT include

- Telephony / SIP / Exotel integration (next phase)
- Temporal durable workflows (next phase)
- Kubernetes / KEDA (next phase)
- PII redaction pipeline (next phase)
- Multi-agent orchestration (future)

---

## 15. System Architecture

### Architectural Flow
```mermaid
graph TD
    User([User Voice]) --> Transport[Transport Layer: WebRTC]
    Transport --> LiveKit[LiveKit SFU / Room Mgmt]
    LiveKit --> Runtime[Voice Runtime: Pipecat Orchestrator]
    
    subgraph "Audio Processing Pipeline"
        Runtime --> VAD[Silero VAD / Resampling]
        VAD --> STT[Deepgram STT]
    end
    
    STT --> LLM[LLM: OpenAI / Ollama]
    LLM --> TTS[TTS: Cartesia]
    
    TTS --> TransportOut[LiveKit Output Transport]
    TransportOut --> User
    
    subgraph "Future Integration Layers"
        SIP[SIP Trunks / PSTN]
        Temporal[Temporal Workflows]
        Tools[Tool Calling / CRM]
    end
```

### 12-Layer Implementation Status

| Layer | Component | Status | Details |
| :--- | :--- | :--- | :--- |
| **1** | **User Voice** | ✅ | Browser Microphone input |
| **2** | **Transport** | ✅ | WebRTC (LiveKit) |
| **3** | **LiveKit / Telephony** | 🟢 | SFU, Room/Participant Mgmt active. SIP/PSTN/Carrier routing is **Roadmap**. |
| **4** | **Voice Runtime** | ✅ | Pipecat 1.1.0 Orchestrator (Session, Lifecycle, Barge-in) |
| **5** | **Audio Pipeline** | ✅ | Silero VAD, Real-time chunking, Resampling |
| **6** | **STT** | ✅ | Deepgram Streaming (Multilingual/Hinglish) |
| **7** | **LLM / Thinking** | 🟢 | Ollama (Local) / OpenAI. RAG & Guardrails are **Roadmap**. |
| **8** | **Tool Calling** | ❌ | Supported by Pipecat; implementation is **Roadmap**. |
| **9** | **Temporal Workflows**| ❌ | Persistence & Failure Recovery is **Roadmap**. |
| **10**| **TTS** | ✅ | Cartesia Streaming (Low-latency synthesis) |
| **11**| **Streaming Output** | ✅ | Jitter compensation & Adaptive playback (LiveKit) |
| **12**| **User Playback** | ✅ | Browser Audio Playback |

---

## 2. Repository Structure

```text
agentOS-poc/
│
├── docker-compose.yml          # Orchestrates all 4 services
├── .env.example                # All env vars with documentation
├── BUILD.md                    # This document
│
├── infra/
│   └── livekit.yaml            # LiveKit server config (local dev)
│
└── services/
    ├── agent/                  # Python FastAPI + Pipecat service
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── config.py           # Pydantic settings; all config from env
    │   ├── main.py             # FastAPI app + session lifecycle
    │   └── pipeline/
    │       ├── agent.py        # Pipecat pipeline + Latency Tuning (0.3s VAD)
    │       └── providers/
    │           ├── stt.py      # STT abstraction (Deepgram / Google Chirp)
    │           ├── tts.py      # TTS abstraction (Cartesia / ElevenLabs)
    │           └── llm.py      # LLM abstraction + system prompt
    │
    └── frontend/
        └── index.html          # Browser voice client (LiveKit JS SDK)
```

---

## 3. Prerequisites

### Required software

|Tool|Minimum version|Install|
|---|---|---|
|Docker Desktop|4.x|https://docs.docker.com/get-docker/|
|Docker Compose|v2 (bundled with Docker Desktop)|Included|
|A modern browser|Chrome 100+ or Firefox 110+|—|

That's it. Python, Node.js, and all other dependencies live inside Docker containers.

### Verify your Docker install

```bash
docker --version        # Should print Docker version 24.x or higher
docker compose version  # Should print Docker Compose version v2.x
```

### Port availability

These ports must be free on your machine. Check with `lsof -i :<port>` on Mac/Linux:

|Port|Service|Protocol|
|---|---|---|
|7880|LiveKit HTTP/WS|TCP|
|7881|LiveKit RTC|TCP|
|7882|LiveKit RTC|UDP|
|6379|Redis|TCP|
|8080|Agent FastAPI|TCP|
|3000|Frontend Nginx|TCP|

---

## 4. API Keys You Need

You need **at minimum** keys for one STT provider, one TTS provider, and one LLM provider. The defaults (Deepgram + Cartesia + OpenAI) are the recommended starting point.

### Deepgram (STT) - Default

1. Sign up at https://console.deepgram.com
2. Create a new project
3. Go to API Keys → Create API Key (give it "Member" role)
4. Copy the key; it starts with something like `token_...`
5. Free tier: $200 credit on signup, enough for extensive testing

### Cartesia (TTS) - Default

1. Sign up at https://play.cartesia.ai
2. Go to API → API Keys → Create new key
3. Copy the key
4. Browse voices at https://play.cartesia.ai/voices; find a voice suitable for Indian English
5. Copy the Voice ID (a UUID like `a0e99841-438c-4a64-b679-ae501e7d6091`)
6. Free tier: generous credits on signup

### Ollama (Local LLM) - Recommended for Dev
1. Install Ollama from https://ollama.com
2. Pull the Qwen model: `ollama pull qwen3.5:9b`
3. The agent connects to Ollama via `http://host.docker.internal:11434/v1`
4. No API key required for local testing!

### OpenAI (LLM) - Alternative
1. Sign up at https://platform.openai.com
2. Go to API Keys → Create new secret key
3. Copy the key; starts with `sk-...`
4. Note: GPT-4o-mini is recommended for the fastest real-time performance.
5. In `.env`, set `LLM_PROVIDER=openai` and `LLM_MODEL=gpt-4o-mini`.

### Alternative: Anthropic Claude (LLM)

1. Sign up at https://console.anthropic.com
2. Go to API Keys → Create Key
3. Set `LLM_PROVIDER=anthropic` and `LLM_MODEL=claude-sonnet-4-20250514` in `.env`

### Alternative: Google Chirp (STT - better Hinglish)

Required only if you want to test Google's dialect support:

1. Create a GCP project at https://console.cloud.google.com
2. Enable the "Cloud Speech-to-Text API"
3. Create a Service Account with Speech Client role
4. Download the JSON credentials file
5. Place it at `services/agent/gcp-credentials.json`
6. Set `STT_PROVIDER=google_chirp` in `.env`

---

## 5. Step-by-Step Setup

### Step 1 - Clone and enter the project

```bash
# If you received this as a zip:
unzip agentOS-poc.zip
cd agentOS-poc

# If using git:
git clone <your-repo-url>
cd agentOS-poc
```

### Step 2 - Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` in any editor and fill in your API keys. At minimum:

```bash
# Required fields for cloud providers
DEEPGRAM_API_KEY=your_actual_deepgram_key
CARTESIA_API_KEY=your_actual_cartesia_key
CARTESIA_VOICE_ID=your_chosen_voice_uuid

# LLM Selection (openai / ollama / anthropic)
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
```

Leave everything else at its defaults for the first run.

### Step 3 - Build the Docker images

```bash
docker compose build
```

This builds the Python agent image. Expect 3–5 minutes on first run (downloading base image + installing Python packages). Subsequent builds are fast due to Docker layer caching.

Watch for any build errors. The most common: pip install failures due to system library mismatches. The Dockerfile already handles these, but if you see errors, check the troubleshooting section.

### Step 4 - Start all services

```bash
docker compose up
```

You should see logs from four services starting. Wait until you see:

```text
livekit     | INFO  starting server ...
agent       | INFO  Application startup complete.
redis       | Ready to accept connections
frontend    | nginx: configuration file ... test is successful
```

To run in background (detached):

```bash
docker compose up -d
docker compose logs -f agent  # Follow just the agent logs
```

### Step 5 - Verify services are running

```bash
# Check all containers are up
docker compose ps

# Test the agent API health endpoint
curl http://localhost:8080/health
```

Expected health response:

```json
{
  "status": "ok",
  "providers": {
    "stt": "deepgram",
    "tts": "cartesia",
    "llm": "ollama"
  },
  "active_sessions": 0
}
```

### Step 6 - Open the browser UI

Navigate to: **http://localhost:3000**

You should see the dark UI with a blue orb and "Ready to connect" status.

### Step 7 - Start a voice session

1. Click **"Connect to Aria"**
2. Your browser will ask for microphone permission; allow it
3. The orb turns blue and pulses; you're live
4. Speak in English or Hinglish
5. The agent responds with voice (and transcript appears in the panel)
6. Click **Disconnect** to end the session

### Step 8 - Confirm it works end-to-end

Try saying: _"Namaste, mera naam Arjun hai. What can you help me with?"_

The agent should respond within ~2–3 seconds (first response is slightly slower due to cold-start model loading). Subsequent responses should be ~300–500ms.

---

## 6. File-by-File Reference

### `docker-compose.yml`

Defines four services:

**livekit** - The WebRTC SFU. Handles all real-time audio routing between the browser and your agent. Runs in `--dev` mode which auto-accepts the dev API keys defined in `livekit.yaml`. Exposes 7880 (HTTP/WS), 7881 (TCP RTC), 7882/udp (UDP RTC).

**redis** - Session state store. Currently used for pub/sub scaffolding. In this POC it's mostly a placeholder. The session registry lives in-memory in `main.py`. When you scale to multiple agent replicas, you'll move the registry here.

**agent** - The FastAPI + Pipecat Python service. This is the brain. It mounts the `./services/agent` directory as a volume, so code changes hot-reload via uvicorn without rebuilding the image.

**frontend** - A plain nginx container serving the single `index.html`. No build step needed. If you modify `index.html`, nginx picks up changes immediately.

### `infra/livekit.yaml`

LiveKit server configuration for local development. Key settings:

- `keys: devkey: devsecret-32-character...` - the dev API key pair. These must match `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` in `.env`.
- `rtc.use_external_ip: false` - critical for local dev.
- `rtc.node_ip: 127.0.0.1` - forces LiveKit to advertise the host loopback so the browser can reach it from outside Docker.
- `turn.enabled: false` - TURN relay is not needed on localhost.

For production, you will replace this file with a config that enables TURN, sets a real domain, and uses proper key rotation.

### `services/agent/config.py`

All configuration lives here as a Pydantic `Settings` class. Every field maps 1:1 to an environment variable. The benefit: if you try to start the service with a missing required key, it fails immediately with a clear error instead of crashing mid-call.

Key settings to understand:

- `LIVEKIT_URL` vs `LIVEKIT_PUBLIC_URL` - two different URLs for the same LiveKit server. `LIVEKIT_URL` is used by the agent container internally (uses Docker service name `livekit`). `LIVEKIT_PUBLIC_URL` is returned to the browser and must be reachable from outside Docker (`localhost`).
- `AGENT_LANGUAGE` - passed to Deepgram. `"multi"` enables automatic language detection. Use `"hi"` for Hindi-only, `"en-US"` for English-only.

### `services/agent/main.py`

The FastAPI application. Three responsibilities:

**POST `/session/join`** — the entry point for every call. It generates a unique session ID, mints two LiveKit JWTs (one for the browser user, one for the agent), spawns a Pipecat pipeline as a background `asyncio.Task`, and returns the user token + room name to the browser.

**Session registry** (`_sessions` dict) — maps session IDs to asyncio Tasks. Allows you to cancel specific sessions via `DELETE /session/:id`. In this POC it's in-memory; for multi-replica deployments it moves to Redis.

**Lifespan handler** — runs on startup and shutdown. On shutdown it cancels all active session tasks, allowing Pipecat to drain its TTS queue and close LiveKit connections cleanly before the process exits.

### `services/agent/pipeline/agent.py`

The core of the system. One instance of `run_agent_session()` runs per active call.

**The pipeline assembly** is the critical section:

```python
pipeline = Pipeline([
    transport.input(),           # Raw PCM from LiveKit
    stt,                         # Transcription
    context_aggregator.user(),   # Append to conversation history
    llm,                         # Generate response tokens
    tts,                         # Synthesize audio
    transport.output(),          # Send audio back via LiveKit
    context_aggregator.assistant(), # Record assistant turn
])
```

Pipecat connects these processors with internal async queues. Audio frames flow left to right. When `allow_interruptions=True`, Pipecat flushes the TTS queue and cancels pending LLM tokens the moment Silero VAD detects the user speaking again.

**The greeting** (`on_first_participant_joined`) sends a `TextFrame` directly into the pipeline, bypassing STT and LLM entirely. This makes the first response instantaneous — it goes straight to TTS and out to the user.

**VAD parameters** to tune:

- `stop_secs=0.5` — how long silence after speech before it's considered end-of-turn. Lower = more responsive but cuts off people who pause mid-sentence. Recommended range: 0.4–0.8s.
- `min_volume=0.6` — filters ambient noise. If the agent triggers on background sounds, raise this. If it misses quiet speakers, lower it.
- `confidence=0.7` — Silero's internal speech/non-speech threshold. Don't change this unless you have a specific reason.

### `services/agent/pipeline/providers/`

Three files, each following the same pattern: a factory function that reads the `*_PROVIDER` env var and returns the appropriate Pipecat service object. This is the provider abstraction layer.

**`stt.py`** — `create_stt_service()` returns either `DeepgramSTTService` or `GoogleSTTService`. Adding a new provider (e.g., Whisper) means adding one `elif` block here and nowhere else.

**`tts.py`** — `create_tts_service()` returns either `CartesiaTTSService` or `ElevenLabsTTSService`. Note the `sample_rate=24000` setting on Cartesia — this must match the `audio_out_sample_rate` in the LiveKit transport params, or you get chipmunk/slowed audio.

**`llm.py`** — `create_llm_service()` plus the `SYSTEM_PROMPT`. The system prompt is the most impactful thing you can tune for POC quality. The key constraint is verbosity: each sentence of LLM output is ~100–200ms of TTS synthesis, so a 5-sentence response adds ~1s of latency before the user hears anything.

### `services/frontend/index.html`

A self-contained single-page app. No framework, no build step. Uses the LiveKit JS SDK loaded from CDN.

The flow on "Connect":

1. Calls `POST /session/join` on the agent API to get a token + room name
2. Creates a `Room` instance with AEC, noise suppression, and auto-gain enabled
3. Connects to LiveKit via the returned token
4. Enables the microphone (triggers browser permission prompt)
5. Listens for `TrackSubscribed` events — when the agent publishes audio, attaches it to a hidden `<audio>` element for playback

The orb animation states correspond to LiveKit room events: `speaking` when agent audio is subscribed, `listening` otherwise.

---

## 7. How the Pipeline Actually Works

Here is the exact sequence of events for a single user turn:

```
00ms  User starts speaking
      └─ Silero VAD detects audio above threshold

      [Audio frames flow through transport.input() at 20ms chunks]

      └─ Deepgram receives streaming audio, begins returning partial transcripts

~200ms User finishes sentence
       └─ 500ms VAD silence timer starts

~700ms VAD fires end-of-turn signal (200ms speech end + 500ms stop_secs)
       └─ Final Deepgram transcript is delivered as a TranscriptionFrame

~720ms context_aggregator.user() appends {"role":"user","content":"..."} to context

~730ms LLM receives full context, begins streaming response tokens

~780ms First token arrives from LLM

~820ms TTS receives first sentence chunk (Pipecat buffers until punctuation boundary)
       └─ Cartesia begins synthesis

~870ms First audio frame returns from Cartesia (~50ms TTFA)
       └─ transport.output() sends frame to LiveKit
       └─ Browser plays audio

Total perceived latency: ~670ms from end-of-speech to first audio
```

**What happens on interruption:**

```
500ms  User starts speaking while agent is still talking
       └─ Silero VAD triggers immediately
       └─ Pipecat flushes TTS audio queue
       └─ Sends CancelFrame to LLM (stops token generation)
       └─ LiveKit stops publishing agent audio

~650ms  STT takes over again
        └─ New turn begins
```

The interruption latency target is ~150ms from the moment Silero fires to the moment agent audio stops. In practice on localhost you'll see 100–200ms.

---

## 8. Provider Swapping Guide

### Switch STT to Google Chirp (better Hinglish)

```bash
# In .env:
STT_PROVIDER=google_chirp
AGENT_LANGUAGE=hi-IN    # or "en-IN" for Indian English
```

You also need GCP credentials:

```bash
# Place your credentials file at:
services/agent/gcp-credentials.json

# Then mount it in docker-compose.yml, under agent volumes:
volumes:
  - ./services/agent:/app
  - ./services/agent/gcp-credentials.json:/app/gcp-credentials.json:ro

# And set the env var:
environment:
  - GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-credentials.json
```

Then restart: `docker compose restart agent`

### Switch TTS to ElevenLabs

```bash
# In .env:
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your_key
ELEVENLABS_VOICE_ID=your_voice_id   # Browse voices at elevenlabs.io
```

Note: ElevenLabs Turbo v2.5 has ~300ms TTFA vs Cartesia's ~70ms. You'll feel the difference. Use ElevenLabs when voice quality and expressiveness matter more than raw speed.

### Switch LLM to Claude

```bash
# In .env:
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key
LLM_MODEL=claude-sonnet-4-20250514
```

Claude tends to produce more naturally conversational short responses, which works better for voice than GPT-4o's tendency toward structured lists. Consider tuning `SYSTEM_PROMPT` in `llm.py` when switching.

### Switch to GPT-4o Mini (lower cost for testing)

```bash
# In .env — just change the model, keep the provider:
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
```

GPT-4o Mini is ~20x cheaper than GPT-4o and adequate for simple voice tasks. Use it while building; switch back to GPT-4o for quality validation.

---

## 9. Testing & Validation

### Test 1 — Health check

```bash
curl http://localhost:8080/health | python3 -m json.tool
```

Expected: `"status": "ok"` with your configured providers listed.

### Test 2 — Session creation (without browser)

```bash
curl -X POST http://localhost:8080/session/join \
  -H "Content-Type: application/json" \
  -d '{"user_identity": "test-user"}' | python3 -m json.tool
```

Expected: a JSON object with `session_id`, `room_name`, `token`, and `livekit_url`. Also verify that `docker compose logs agent` shows a `session.start` log line and a `participant.joined` line shortly after (the agent joins the room automatically).

### Test 3 — List active sessions

```bash
curl http://localhost:8080/sessions
```

While a session is active (browser connected), you should see it here. After disconnect, it should drop to 0.

### Test 4 — End-to-end voice quality checklist

Use this list when evaluating the POC:

- [ ] Greeting is delivered within 1 second of browser connecting
- [ ] User speech is transcribed correctly (check console logs on agent)
- [ ] Agent responds within ~500ms of user finishing a sentence
- [ ] Hinglish phrase like "mujhe kal 3 baje ke liye appointment chahiye" is understood correctly
- [ ] Interrupting the agent mid-sentence stops playback within ~200ms
- [ ] After interruption, agent correctly processes the new user input
- [ ] Disconnecting from browser cleanly removes the session (check `/sessions`)

### Test 5 — Latency measurement

Open browser DevTools → Network tab before connecting. After a few turns:

1. Look for the `/session/join` request timing — should be under 500ms
2. In the agent logs: look for `session.start` → `participant.joined` gap — should be under 150ms
3. Subjectively: first audio after speaking should arrive within 1–2 seconds

For precise per-component latency, see Section 10.

---

## 10. Latency Benchmarking

The POC emits OpenTelemetry metrics when `enable_metrics=True` in the pipeline task. To see them:

### Quick console benchmark

Temporarily add timing logs to `pipeline/agent.py`:

```python
# In the on_first_participant_joined handler, after capture_participant_audio:
import time

# Record when user turn starts (VAD fires)
# Pipecat's PipelineTask emits metrics — read them from the runner
```

For a more practical approach during POC, watch the agent Docker logs:

```bash
docker compose logs -f agent 2>&1 | grep -E "stt|tts|llm|session"
```

### Benchmark targets for this POC

|Metric|Target|How to measure|
|---|---|---|
|Session join latency|< 500ms|`/session/join` API response time|
|Agent join to room|< 150ms|agent log: `session.start` → `participant.joined`|
|VAD stop to STT final|< 300ms|Tuned to 0.3s stop_secs|
|LLM first token|< 400ms|gpt-4o-mini TTFT|
|TTS TTFA (Cartesia)|< 150ms|Time from text to first audio frame|
|Total E2E (end of speech → first audio)|< 800ms|Perceived in browser|

The 1500ms target is achievable on localhost. Over a real network, budget an additional 50–200ms per network hop.

---

## 11. Common Failures & Fixes

### "Connection refused" on the browser after clicking Connect

**Cause:** Agent service hasn't fully started yet, or there's a port conflict.

**Fix:**

```bash
docker compose ps                   # Check all services show "running"
curl http://localhost:8080/health   # Should return 200
lsof -i :8080                       # Check nothing else is on port 8080
```

### Browser shows "Connection failed" and the orb goes red

**Cause 1:** CORS issue — browser rejects the API call.

**Fix:** The FastAPI app has `CORSMiddleware` with `allow_origins=["*"]`. Confirm this is active:

```bash
curl -I -X OPTIONS http://localhost:8080/session/join \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST"
# Should return 200 with Access-Control-Allow-Origin header
```

**Cause 2:** Microphone permission denied in browser.

**Fix:** Click the lock icon in Chrome's address bar → reset microphone permission → reload page.

### Agent joins room but no audio plays

**Cause:** Audio track isn't being attached to the DOM.

**Fix:** Open browser DevTools → Console. Look for errors. The `TrackSubscribed` event in `index.html` creates an `<audio>` element and calls `track.attach()` — check if this is firing.

Also check: `autoplay` is set on the audio element. Some browsers block autoplay without user interaction. Clicking the Connect button counts as user interaction — this should not be an issue.

### STT transcription is empty or wrong

**Cause 1:** Deepgram API key is invalid or missing.

**Fix:**

```bash
docker compose logs agent | grep "deepgram\|stt"
```

If you see `401` or `403`, the key is wrong. Regenerate at console.deepgram.com.

**Cause 2:** Audio sample rate mismatch.

**Fix:** The LiveKit transport is configured with `audio_in_sample_rate=16000`. Deepgram Nova-3 expects 16kHz. If you changed this, revert it.

**Cause 3:** `AGENT_LANGUAGE` mismatch.

**Fix:** Set `AGENT_LANGUAGE=multi` in `.env` for Hinglish. The `multi` value enables Deepgram's automatic language detection.

### TTS audio sounds distorted / too fast / too slow

**Cause:** Sample rate mismatch between TTS output and LiveKit transport.

**Fix:** Ensure `audio_out_sample_rate=24000` in `pipeline/agent.py` matches Cartesia's output sample rate. Cartesia Sonic outputs 24kHz by default. If you switched to ElevenLabs, it outputs 22050Hz — update the transport param accordingly:

```python
# In pipeline/agent.py, for ElevenLabs:
audio_out_sample_rate=22050,
```

### "WebRTC connection failed" — no audio at all

**Cause:** ICE candidate negotiation failing. Common on Linux with unusual network configs.

**Fix:** Add your network interface to `infra/livekit.yaml`:

```yaml
rtc:
  interfaces:
    includes:
      - lo
      - eth0
      - ens3      # Add your actual interface name
      - wlo1      # Add Wi-Fi interface if different
```

Find your interface name: `ip addr show` on Linux, `ifconfig` on Mac.

Then restart: `docker compose restart livekit`

### Agent crashes with `ImportError` on startup

**Cause:** Pipecat integration package not installed. Pipecat uses optional extras.

**Fix:** Check `requirements.txt` — the install line must include the providers you're using:

```
pipecat-ai[silero,deepgram,cartesia,elevenlabs,openai,anthropic,livekit]
```

If you added a new provider after the image was built:

```bash
docker compose build --no-cache agent
docker compose up agent
```

### High latency (>3 seconds)

**Cause 1:** VAD `stop_secs` too high. At 0.5s, you wait 500ms after speech ends before the turn is committed. This is the single biggest contributor to perceived latency.

**Fix for testing:** Try `stop_secs=0.3` in `pipeline/agent.py`. This reduces wait time but increases false triggers on pauses.

**Cause 2:** LLM generating long responses.

**Fix:** The system prompt says "1-3 sentences MAXIMUM" but LLMs sometimes ignore this. Add temperature and max_tokens constraints:

```python
# In providers/llm.py for OpenAI:
return OpenAILLMService(
    api_key=settings.openai_api_key,
    model=settings.llm_model,
    max_tokens=150,    # ~1-2 sentences
    temperature=0.7,
)
```

**Cause 3:** Docker networking overhead. On Docker Desktop for Mac, the network stack adds ~20–50ms per call. This is normal and doesn't reflect production latency.

---

## 12. Extending the POC

### Add a tool call (e.g., checking calendar availability)

In `pipeline/providers/llm.py`, define a tool schema and register it with Pipecat's LLM function calling:

```python
from pipecat.services.openai import OpenAILLMService
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContextFrame

# Define your tool
tools = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check if a time slot is available for booking",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "time": {"type": "string", "description": "Time in HH:MM format"}
                },
                "required": ["date", "time"]
            }
        }
    }
]

# Pass tools to LLM service
return OpenAILLMService(
    api_key=settings.openai_api_key,
    model=settings.llm_model,
    tools=tools,
)
```

Then register the function handler in `pipeline/agent.py`:

```python
# In run_agent_session(), after creating the llm service:
@llm.event_handler("on_function_call")
async def handle_function_call(llm, function_name, arguments, result_callback):
    if function_name == "check_availability":
        # Your business logic here
        result = {"available": True, "slots": ["3:00 PM", "4:00 PM"]}
        await result_callback(result)
```

### Add Redis session state persistence

Currently the session registry is in-memory. To survive agent restarts:

```python
# In main.py, add Redis session writes:
import redis.asyncio as aioredis

redis_client = aioredis.from_url(settings.redis_url)

async def join_session(req):
    # ... existing logic ...
    await redis_client.hset(
        f"session:{session_id}",
        mapping={
            "room_name": room_name,
            "user_identity": req.user_identity,
            "started_at": str(time.time()),
        }
    )
    await redis_client.expire(f"session:{session_id}", 3600)  # 1 hour TTL
```

### Add transcript logging

In `pipeline/agent.py`, add a Pipecat observer to log every transcript:

```python
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.frames.frames import TranscriptionFrame, TTSTextFrame

class TranscriptLogger(BaseObserver):
    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        if isinstance(frame, TranscriptionFrame):
            logger.info(f"transcript.user: {frame.text}")
        elif isinstance(frame, TTSTextFrame):
            logger.info(f"transcript.agent: {frame.text}")

# In run_agent_session, before creating the runner:
task.add_observer(TranscriptLogger())
```

### Add Temporal for durable workflows (next phase)

When the agent needs to call a backend system that might fail or take more than 2 seconds, wrap it in a Temporal Activity instead of a direct API call. This prevents the voice session from hanging on slow backend calls.

The separation is clean: the Pipecat pipeline handles the real-time voice loop, and the Temporal worker handles the business logic. They communicate via a shared task queue in Redis.

---

## 13. Production Readiness Checklist

The POC is not production-ready. Here is what you need to address before going to production:

### Security

- [ ] Replace dev LiveKit keys (`devkey`/`devsecret`) with real generated keys
- [ ] Move all API keys to a secrets manager (AWS Secrets Manager, GCP Secret Manager, or Vault)
- [ ] Remove `allow_origins=["*"]` from FastAPI CORS config; whitelist your actual domain
- [ ] Add authentication to the `/session/join` endpoint (JWT, API key, or session cookie)
- [ ] Enable DTLS/SRTP on LiveKit (enabled by default — verify your production config doesn't disable it)
- [ ] Add rate limiting to the session join endpoint (prevent session bombing)

### PII & Compliance

- [ ] Add Transcribe-First-Then-Redact pipeline before storing any transcripts
- [ ] Do not log raw transcripts in plaintext — hash or encrypt them
- [ ] If HIPAA/GDPR applies: data residency constraints on which cloud regions can process audio
- [ ] Implement transcript retention policy and deletion workflows

### Infrastructure

- [ ] Move from Docker Compose to Kubernetes (GKE Autopilot recommended)
- [ ] Add `preStop` lifecycle hooks to worker pods (150s sleep) to prevent mid-call pod kills
- [ ] Add KEDA autoscaling bound to session queue depth — not CPU
- [ ] Enable LiveKit TURN server (required for enterprise networks with strict firewalls)
- [ ] Add a proper domain + TLS termination in front of LiveKit and the agent API
- [ ] Move session registry from in-memory dict to Redis (required for multi-replica deployments)

### Observability

- [ ] Wire OpenTelemetry traces to a real backend (Grafana Tempo, Jaeger, or Datadog)
- [ ] Add Langfuse for LLM trace analysis (prompt quality, tool failure debugging)
- [ ] Set up Prometheus + Grafana for TTFA, WER, and E2E latency dashboards
- [ ] Add per-session cost tracking (Deepgram minutes + Cartesia characters + OpenAI tokens)

### Resilience

- [ ] Add provider fallback: if Cartesia fails, fall back to ElevenLabs automatically
- [ ] Add circuit breakers on LLM API calls with graceful "I'm having trouble, please try again" TTS responses
- [ ] Configure Temporal for all backend tool calls
- [ ] Test pod restart mid-call — verify the session terminates gracefully (not abruptly)

---

## 14. Architecture Decision Log

These decisions were made for the POC. Each has a documented rationale and upgrade path.

### LiveKit over Agora or Daily

**Reason:** LiveKit's open-source server enables fully self-hosted deployments with no per-minute platform fees. For the POC, the dev mode makes local testing trivial. For India production, LiveKit self-hosted on Mumbai region bare metal costs ~$0.01–0.03/session vs Agora's $0.0265/participant-minute with bundled charges. LiveKit also has native Pipecat integration maintained by the Pipecat team.

**Upgrade path:** LiveKit Cloud Enterprise tier when you need managed global edge routing without ops overhead.

### Pipecat over LiveKit Agents or Vapi

**Reason:** Pipecat is transport-agnostic. When you add SIP/PSTN telephony (Exotel), you don't need to rewrite the pipeline — you swap the transport processor. LiveKit Agents framework tightly couples orchestration to LiveKit. Vapi is a black box with no provider swap capability.

**Upgrade path:** None needed. Pipecat scales to multi-agent architectures natively.

### Silero VAD over energy-based VAD

**Reason:** Energy-based VAD fires on any loud sound — AC noise, keyboard clicks, background TV. Silero is a lightweight neural model (~2MB) that actually detects human speech. The difference in false-positive rate is significant in a typical Indian home/office environment with ceiling fans and ambient traffic noise.

**Upgrade path:** Phoenix-VAD (semantic endpointing) when you need to handle pauses within sentences correctly. Phoenix-VAD evaluates syntactic completeness of the transcript in addition to audio energy — it won't cut off a user who says "mujhe aaj..." and then pauses to think.

### Deepgram Nova-3 as default STT over Google Chirp

**Reason:** Deepgram requires only an API key — zero GCP setup. For the POC, getting to a working demo quickly is more important than best-in-class Hinglish accuracy. Nova-3 with `language=multi` handles most everyday Hinglish adequately.

**Upgrade path:** Switch `STT_PROVIDER=google_chirp` when you encounter dialect failures in testing. Google Chirp has significantly better coverage of regional Indian phonetics and code-switching.

### In-memory session registry over Redis

**Reason:** For a single-node POC, an in-memory dict is simpler, faster, and has zero ops overhead. Redis adds latency and a dependency for no benefit at this scale.

**Upgrade path:** When you run multiple agent replicas (required for production), move to Redis hash sets with TTL. The interface in `main.py` is already designed to make this a clean swap.

### asyncio.Task per session over Temporal

**Reason:** Temporal adds significant complexity (separate worker process, Temporal server, workflow + activity definitions). For a voice session without long-running backend tasks, asyncio.Task provides the same session isolation at zero overhead.

**Upgrade path:** Wrap backend tool calls in Temporal Activities when those tools can fail, are slow (>2 seconds), or require retry/compensation logic (e.g., booking systems, payment APIs). The voice loop stays in asyncio; only the side-effects move to Temporal.

---

Document version: 0.1.0 
