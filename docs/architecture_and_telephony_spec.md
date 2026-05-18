# VREP Phase 2: Architectural & Telephony Specification

**Voice Runtime Evaluation Platform (VREP)** is a highly modular, containerized multi-mode evaluation environment engineered for comparative testing of cognitive voice assistant runtimes. This document details the exact technical implementation of the three isolated runtime architectures and outlines the production blueprint for PSTN/SIP telephony integration.

---

## 1. Executive Microservice Topology & Unified Ingress

To overcome cloud tunneling constraints (where cloud development environments restrict open ports to single endpoints), VREP establishes a **Unified Single-Port Reverse Proxy** using Nginx on Port 3000.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL BROWSER / TELEPHONY CLIENT                             │
│                         (Connects over HTTP/WS Port 3000)                              │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        NGINX UNIFIED REVERSE PROXY (Port 3000)                         │
├──────────────────────┬────────────────────────┬─────────────────────┬──────────────────┤
│ Static UI (`/`)      │ Session Router Gateway │ Debug Timeline WS   │ LiveKit WebRTC   │
│                      │ (`/session/join`)      │ (`/debug/ws`)       │ (`/livekit/`)    │
└──────────┬───────────┴───────────┬────────────┴──────────┬──────────┴────────┬─────────┘
           │                       │                       │                   │
           ▼                       ▼                       ▼                   ▼
┌──────────────────────┐┌───────────────────────┐┌────────────────────┐┌─────────────────┐
│ STATIC UI BUNDLE     ││ SESSION ROUTER        ││ EVENT BRIDGE       ││ LIVEKIT SERVER  │
│ (/usr/share/nginx/..)││ (FastAPI Port 8000)   ││ (FastAPI Port 8090)││ (Port 7880)     │
└──────────────────────┘└──────────┬────────────┘└─────────▲──────────┘└───────▲─────────┘
                                   │                       │                   │
                                   ▼                       │                   │
                       ┌───────────────────────────────┐   │                   │
                       │ MODE 1 / MODE 2 / MODE 3      │   │                   │
                       │ AGENT RUNTIME CONTAINERS      │───┴───────────────────┘
                       │ (Ports 8081 / 8082 / 8083)    │
                       └───────────────────────────────┘
```

### Ingress Routing Rules
- **`/`**: Serves the precompiled static Vanilla HTML/CSS/JS frontend application.
- **`/session/join`**: Proxies HTTP POST requests to `session-router:8000`. The router generates dynamic LiveKit room names, user/agent participant tokens, and dispatches an initialization command to the correct backend container (`agent-mode1`, `agent-mode2`, or `agent-mode3`).
- **`/debug/ws`**: Proxies WebSocket connections to `event-bridge:8090`. The Event Bridge polls Redis streams (`active_streams` maintaining exact offsets) and broadcasts real-time telemetry events to the frontend timeline UI.
- **`/livekit/`**: Proxies WebRTC signaling, ICE negotiation, and data channel traffic to `livekit:7880`.

---

## 2. Mode 1 Architecture: LiveKit Agents SDK (`services/agent-mode1`)

Mode 1 represents a pure implementation built upon the official `livekit-agents` SDK framework, utilizing `VoicePipelineAgent` and `voice.AgentSession`.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    MODE 1: LIVEKIT AGENT RUNTIME                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────────┐      Audio PCM      ┌──────────────────────┐  │
│  │ LiveKit RTC Track    │────────────────────►│ Deepgram STT Plugin  │  │
│  └──────────────────────┘                     └──────────┬───────────┘  │
│             ▲                                            │ Text         │
│  Audio PCM  │                                            ▼              │
│  ┌──────────────────────┐     Text Tokens     ┌──────────────────────┐  │
│  │ Cartesia TTS Plugin  │◄────────────────────│ OpenAI LLM Service   │  │
│  └──────────────────────┘                     └──────────────────────┘  │
│                                                          │              │
│                                                          ▼              │
│                                               ┌──────────────────────┐  │
│                                               │ Native Function Call │  │
│                                               │ (`check_avail...`)   │  │
│                                               └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Core Implementation Mechanics
1. **HTTP Job Session Invariant**: When launching agents outside the standard daemonized CLI worker, LiveKit plugins (`Cartesia`, `Deepgram`) require an active aiohttp context. Mode 1 wraps its entire execution tree inside `async with livekit.agents.utils.http_context.open():`, preventing runtime instantiation failures.
2. **Participant Token Permissions**: To allow the backend agent to negotiate room metadata and publish synthesized audio tracks, tokens are minted with explicit VideoGrants: `can_publish=True, can_subscribe=True, can_publish_data=True, can_update_own_metadata=True, agent=True`.
3. **Data Channel State Synchronization**: In `livekit-agents`, interaction states (`LISTENING`, `THINKING`, `RESPONDING`) and assistant text payloads must be explicitly mirrored over custom data channels. Mode 1 hooks `agent_state_changed` to publish empty assistant turn packets (triggering UI bubbles) and hooks `conversation_item_added` to broadcast finalized AI transcripts.
4. **Telemetry Bridging**: A custom `TelemetryAdapter` attaches to internal LiveKit agent event handlers (`on_user_started_speaking`, `on_user_stopped_speaking`, `on_agent_started_speaking`, `on_agent_stopped_speaking`), emitting nanosecond-stamped Redis stream events (`user.speech.start`, `llm.request.start`, etc.) with perfect trace ID continuity.

---

## 3. Mode 2 Architecture: Pipecat 1.2.0 (`services/agent-mode2`)

Mode 2 represents a pure frame-based streaming architecture built on `pipecat-ai` 1.2.0, utilizing `PipelineTask`, `PipelineRunner`, and `LiveKitTransport`.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                               MODE 2: PIPECAT PIPELINE                                  │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────┐   AudioRaw   ┌──────────────┐  Transcription   ┌───────────────────┐  │
│  │ LiveKitInput │─────────────►│ Deepgram STT │─────────────────►│ User EventEmitter │  │
│  └──────────────┘              └──────────────┘                  └─────────┬─────────┘  │
│                                                                            │ Text       │
│                                                                            ▼            │
│  ┌──────────────┐   AudioRaw   ┌──────────────┐      Text        ┌───────────────────┐  │
│  │ LiveKitOutput│◄─────────────│ Cartesia TTS │◄─────────────────│ OpenAILLM Service │◄─┤
│  └──────────────┘              └──────────────┘                  └─────────▲─────────┘  │
│         │                                                                  │ Text       │
│         ▼ AudioRaw                                                         │            │
│  ┌─────────────────────────┐     Text     ┌────────────────────────┐       │            │
│  │ Assistant EventEmitter  │─────────────►│ Assistant Aggregator   │───────┘            │
│  └─────────────────────────┘              └────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Core Implementation Mechanics
1. **Bimodal Frame Interception**: In Pipecat, placing a single event emitter after the STT node causes `LLMUserContextAggregator` to consume text frames before they can be observed. Mode 2 solves this by deploying two independent `EventEmitterProcessor` instances: `user_event_processor` placed directly after STT, and `assistant_event_processor` placed after output transport. This guarantees flawless Redis stream telemetry parity with Mode 1.
2. **Sample Rate Synchronization**: Default `LiveKitParams` initialize `audio_out_sample_rate` to `None`. When `CartesiaTTSService` inherits this null value during `StartFrame` negotiation, it attempts to synthesize with `"sample_rate": 0`, resulting in silent connections. Mode 2 explicitly sets `sample_rate=24000` on both `CartesiaTTSService` and `LiveKitParams`, locking the PCM stream at 24kHz.
3. **Verbal Greeting Bypass**: Standard `TextFrame`s queued into the pipeline source are intercepted and consumed by `OpenAILLMService` as input context. Mode 2 queues `TTSSpeakFrame(greeting)` upon room entry (`on_first_participant_joined`), bypassing the LLM and flowing directly to Cartesia for immediate voice playback.
4. **Pipecat 1.2.0 Invariants**: Event handlers and tool definitions strictly adhere to 1.2.0 signatures:
   - Tool callbacks utilize `async def _handle_tool(params: FunctionCallParams)`.
   - Event handlers employ robust attribute resolution `getattr(participant, "identity", str(participant))` to prevent crash loops when dealing with varying SDK participant object representations.

---

## 4. Mode 3 Architecture: Hybrid Runtime (`services/agent-mode3`)

Mode 3 is a custom asynchronous orchestrator designed for absolute granular control over cognitive buffering, non-blocking audio chunking, and multi-turn interruptions.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              MODE 3: HYBRID ORCHESTRATOR                                │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌───────────────────────┐                                                              │
│  │ LiveKit Audio Inbound │──┐                                                           │
│  └───────────────────────┘  │ Async PCM Chunks                                          │
│                             ▼                                                           │
│                  ┌──────────────────────┐  Final Transcript   ┌──────────────────────┐  │
│                  │ Deepgram STT Buffer  │────────────────────►│ Cognitive State Loop │  │
│                  └──────────────────────┘                     └──────────┬───────────┘  │
│                             ▲                                            │ LLM Tokens   │
│           Barge-In Intercept│                                            ▼              │
│  ┌───────────────────────┐  │ Async PCM Chunks                ┌──────────────────────┐  │
│  │ LiveKit Audio Outbound│◄─┴─────────────────────────────────│ Cartesia TTS Buffer  │  │
│  └───────────────────────┘                                    └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Core Implementation Mechanics
1. **Asynchronous Ring Buffers**: Audio input from WebRTC tracks is continuously captured into an asynchronous deque. Deepgram STT operates over this buffer, firing interim and final transcript callbacks.
2. **Cognitive State Machine**: Instead of relying on monolithic SDK loops, Mode 3 maintains an explicit internal state (`IDLE`, `LISTENING`, `BUFFERING`, `SYNTHESIZING`, `SPEAKING`). When a final user transcript arrives, the state transitions to `BUFFERING`, dispatching an async request to OpenAI.
3. **Zero-Latency Interruption**: During assistant audio playback (`SPEAKING`), incoming STT interim frames are continuously evaluated against an acoustic energy threshold. If a valid user barge-in is detected, Mode 3 immediately flushes the TTS audio buffer, cancels any pending LLM token generators, and transmits an interruption data channel packet to the frontend UI.

---

## 5. Telephony Integration Blueprint (PSTN / SIP Trunking)

To extend VREP from a web-based evaluation environment to an enterprise-grade telephony platform, the system integrates standard **SIP Ingress & Trunking** directly into LiveKit's WebRTC media server.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                TELEPHONY INGRESS PIPELINE                               │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────────────┐       SIP Invite (RFC 3261)        ┌───────────────────────┐  │
│  │ PSTN / Cellular User │───────────────────────────────────►│ Twilio SIP Trunk / SBC│  │
│  └──────────────────────┘                                    └───────────┬───────────┘  │
│                                                                          │              │
│                                               SIP/RTP over TLS (Port 5061)              │
│                                                                          ▼              │
│  ┌──────────────────────┐  WebRTC Media (Opus 24kHz)         ┌───────────────────────┐  │
│  │ LiveKit WebRTC Room  │◄───────────────────────────────────│ LiveKit SIP Gateway   │  │
│  └──────────┬───────────┘                                    └───────────────────────┘  │
│             │                                                                           │
│             ▼ Internal WebRTC Signaling                                                 │
│  ┌──────────────────────────────────────────────────┐                                   │
│  │ VREP Mode 1 / Mode 2 / Mode 3 Backend Containers │                                   │
│  └──────────────────────────────────────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1. SIP Ingress Architecture (`sip.livekit.io`)
- **SIP Trunking Provider**: VREP connects to public PSTN networks via Tier-1 SIP trunking providers (e.g., Twilio SIP Trunking, Telnyx, or an internal AudioCodes SBC).
- **LiveKit SIP Gateway**: LiveKit Server provides an integrated SIP Inbound Gateway (`sip.livekit.io` / `sip-inbound` configuration). When a user dials the public phone number, the SIP Trunk dispatches an RFC 3261 `SIP INVITE` over TLS (Port 5061) to the LiveKit SIP Gateway.
- **Room Mapping**: The LiveKit SIP Gateway maps the incoming caller's phone number (`From` URI) and dialed number (`To` URI) to a unique LiveKit room name (`room-sip-<caller_id>`). It instantiates an audio-only WebRTC participant representing the caller and connects them to the room.

### 2. Audio Transcoding & Codec Optimization
PSTN telephony networks operate strictly over narrowband or wideband legacy codecs, whereas VREP cognitive engines synthesize premium wideband audio.
- **Upstream (PSTN -> LiveKit)**: Inbound telephony audio arrives encoded in G.711 PCMU (u-law) or PCMA (a-law) at 8,000 Hz. The LiveKit SIP Gateway dynamically transcodes this G.711 stream into an Opus wideband audio track before publishing it to the room. Deepgram STT services in Modes 1, 2, and 3 seamlessly ingest this Opus track.
- **Downstream (LiveKit -> PSTN)**: When `CartesiaTTSService` synthesizes 24,000 Hz wideband PCM audio, LiveKit packages it into Opus WebRTC frames. The LiveKit SIP Gateway transcodes these Opus frames down to G.711 8kHz RTP packets before transmitting them over the SIP Trunk to the cellular caller.

### 3. DTMF Tone & Signaling Handling
In telephony environments, users frequently interact using keypad inputs (DTMF) for PIN verification, menu selection, or account entry.
- **RFC 2833 / RFC 4733 Payload Translation**: The LiveKit SIP Gateway intercepts inbound RTP DTMF event packets (or SIP `INFO` requests) from the cellular network.
- **Data Channel Transformation**: LiveKit translates these DTMF events into standardized LiveKit data channel messages (`type: "dtmf", tone: "5"`).
- **Agent Interception**: VREP backend containers listen for data channel packets. When a DTMF tone packet is received during an active prompt, the agent runtime immediately appends the digit to the internal user context buffer (`pending_appointment["pin"] += tone`), pausing speech synthesis if necessary.

### 4. Telephony Latency Budgeting
Because PSTN cellular links introduce inherent propagation delay (150ms - 250ms), VREP optimizes the cognitive pipeline to preserve conversational fluidity:
- **VAD Tuning**: Silero VAD parameters across all modes are tightened (`stop_secs=0.35`, `min_volume=0.3`) to prevent cellular background static from triggering false barge-ins while ensuring instant turn-taking when the caller stops speaking.
- **Aggressive STT Endpointing**: Deepgram's interim word timestamps are utilized to anticipate turn completion, allowing the LLM prompt to begin executing 100ms before the final trailing silence buffer expires.

---

## 6. Verification Matrix

| Feature / Metric | Mode 1 (LiveKit SDK) | Mode 2 (Pipecat 1.2) | Mode 3 (Hybrid Runtime) | Telephony (SIP Trunk) |
| :--- | :--- | :--- | :--- | :--- |
| **Cognitive Engine** | OpenAI + Cartesia | OpenAI + Cartesia | OpenAI + Cartesia | Mode 1 / 2 / 3 Backends |
| **Telemetry Hook** | `TelemetryAdapter` | Dual `EventEmitter` | `PipelineBroadcaster` | Redis Stream Mirror |
| **Audio Output** | Wideband 24kHz | Wideband 24kHz | Wideband 24kHz | Transcoded G.711 8kHz |
| **Interruption** | SDK Barge-In | Pipecat Interruption | Granular Audio Flush | Audio Flush + DTMF Intercept |
| **Signaling** | LiveKit WebRTC | LiveKit WebRTC | LiveKit WebRTC | SIP over TLS / RTP |
