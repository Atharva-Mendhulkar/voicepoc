# VREP Phase 2: Component Function Implementation Guide

This guide provides an exhaustive code-level breakdown of exactly how each component, module, and function is implemented across the **Voice Runtime Evaluation Platform (VREP)** codebase. It details the internal logic, async mechanics, data structures, and cross-service communication patterns for every microservice.

---

## 1. The Shared Telemetry Engine (`shared/telemetry.py`)

The telemetry engine acts as the unified observation layer across all three agent runtimes, ensuring that metrics, speech latencies, and tool invocations are standardized before being written to Redis streams.

```python
class TelemetryEmitter:
    def __init__(self, session_id: str, mode: int, runtime: str): ...
    async def emit(self, event_name: str, payload: dict): ...
```

### Function Implementation Mechanics
- **`__init__(session_id, mode, runtime)`**: Initializes an async connection pool to the Redis container (`redis:6379`). It caches the `session_id` (used as the Redis stream key suffix `telemetry:<session_id>`), the architectural `mode` (1, 2, or 3), and the string `runtime` identifier (`livekit`, `pipecat`, or `hybrid`).
- **`emit(event_name, payload)`**: Constructs a nanosecond-precision timestamp (`time.time_ns()`), generates a unique trace ID (`uuid.uuid4().hex`), and packages the payload into a standardized dictionary containing `{"timestamp": ..., "mode": ..., "runtime": ..., "event": event_name, "payload": json.dumps(payload)}`. It asynchronously executes `redis.xadd(f"telemetry:{self.session_id}", entry)` to append the event to the session's Redis stream.

---

## 2. The Session Gateway (`services/session-router/main.py`)

The Session Router is a high-concurrency FastAPI gateway responsible for minting LiveKit rooms, negotiating participant tokens, and dispatching initialization signals to backend agent containers.

```python
@app.post("/session/join")
async def join_session(req: JoinSessionRequest): ...
```

### Function Implementation Mechanics
- **Room ID & Token Minting**: When a user selects a mode and clicks Connect, the frontend sends an HTTP POST request to `/session/join`. The gateway generates a unique LiveKit room identifier (`room-<UUID>`).
- **LiveKit SDK `AccessToken` Generation**: Using `AccessToken(api_key, api_secret)`, it generates two distinct JWTs:
  1. **User Token**: Minted with `VideoGrants(room_join=True, room=room_id, can_publish=True, can_subscribe=True, can_publish_data=True)`.
  2. **Agent Token**: Minted with `VideoGrants(room_join=True, room=room_id, can_publish=True, can_subscribe=True, can_publish_data=True, can_update_own_metadata=True, agent=True)`. The `can_update_own_metadata` and `agent=True` flags are critical invariants required by LiveKit Server v1.8+ for backend agent track publishing.
- **Backend Container Warmup**: Based on the requested mode (`req.mode`), the router issues an async HTTP POST request (`/start`) to the corresponding internal container (`agent-mode1:8081`, `agent-mode2:8082`, or `agent-mode3:8083`), passing the generated `session_id`, `room_id`, and `agent_token`.

---

## 3. The Event Bridge (`services/event-bridge/main.py`)

The Event Bridge is a specialized asynchronous WebSocket server that bridges Redis backend streams directly to the frontend timeline UI in real time.

```python
@app.websocket("/ws/events/{session_id}")
async def event_stream_endpoint(websocket: WebSocket, session_id: str): ...
```

### Function Implementation Mechanics
- **WebSocket Handshake & Connection Guard**: Accepts incoming WebSocket connections on `/ws/events/{session_id}`.
- **`active_streams` Offset Synchronization**: To prevent dropped events during UI timeline re-renders or temporary reconnects, the bridge maintains an exact dictionary of Redis stream offsets (`active_streams = {stream_key: "0"}`). Starting from offset `"0"` ensures that connecting clients instantly receive all historical lifecycle events that occurred prior to connecting.
- **Async Polling Loop (`redis.xread`)**: Executes an infinite `while True:` loop calling `await redis.xread({stream_key: current_offset}, count=50, block=100)`. When new entries are returned, it iterates over the stream records, updates `current_offset` to the exact message ID (`1716...-0`), and broadcasts the JSON payload over `await websocket.send_text(json.dumps(event))`.

---

## 4. Mode 1 Agent Runtime (`services/agent-mode1/runtime/agent.py`)

Mode 1 is implemented using the official `livekit-agents` framework, orchestrating `VoicePipelineAgent` within an asynchronous event loop.

```python
async def run_livekit_session(session_id: str, room_name: str, agent_token: str): ...
```

### Function Implementation Mechanics
- **`http_context.open()` Execution Boundary**: LiveKit plugins (`Cartesia`, `Deepgram`) require an active aiohttp client context. The main session initialization is enclosed inside `async with livekit.agents.utils.http_context.open():`.
- **Agent Initialization**: Instantiates `voice.VoicePipelineAgent` with `vad=silero.VAD.load()`, `stt=deepgram.STT()`, `llm=openai.LLM()`, and `tts=cartesia.TTS(voice="248be419-...")`.
- **Data Channel State Broadcasting**:
  - Hooks `@agent.on("agent_state_changed")`. When the internal state machine transitions to `LISTENING` or `THINKING`, it broadcasts a WebRTC data channel packet (`json.dumps({"type": "transcription", "participant": "agent", "text": ""})`) to render the interactive UI typing bubbles.
  - Hooks `@agent.on("conversation_item_added")`. When a finalized AI prompt is generated, it extracts the content and broadcasts the completed transcript to the room.
- **Telemetry Bridging (`TelemetryAdapter`)**: Attaches event listeners to internal agent lifecycle hooks (`on_user_started_speaking`, `on_agent_started_speaking`, `on_function_call`). Each hook executes `await telemetry.emit(...)` to ensure nanosecond continuity across Redis streams.

---

## 5. Mode 2 Pipecat Runtime (`services/agent-mode2/pipeline/agent.py`)

Mode 2 is a pure frame-based streaming architecture built on `pipecat-ai` 1.2.0, utilizing custom `FrameProcessor` nodes.

```python
async def run_pipecat_session(session_id: str, room_name: str, agent_token: str): ...
```

### Function Implementation Mechanics
- **`EventEmitterProcessor(FrameProcessor)`**: A custom pipeline processor placed before and after the LLM aggregator nodes.
  - In `process_frame(frame, direction)`: If `frame` is `UserStartedSpeakingFrame`, it emits `user.speech.start`. If `TranscriptionFrame`, it broadcasts a data channel packet (`{"type": "transcription", "text": frame.text, "is_final": True}`) and emits `user.transcript.final`. If `TextFrame` or `TTSStartedFrame`, it records TTFT (Time-To-First-Token) and TTFA (Time-To-First-Audio) metrics.
- **Bimodal Emitter Placement**: To prevent `LLMUserContextAggregator` from swallowing `TranscriptionFrame`s before they can be observed, Mode 2 instantiates two distinct emitters: `user_event_processor` placed directly after `stt`, and `assistant_event_processor` placed after `transport.output()`.
- **Sample Rate Locking**: Configures `audio_out_sample_rate=24000` in `LiveKitParams` and `sample_rate=24000` in `CartesiaTTSService`. This guarantees that Cartesia's WebSocket handshake receives `"sample_rate": 24000` during `StartFrame` negotiation, preventing silent drops.
- **`on_first_participant_joined(transport, participant)`**: Hooks room entry. It extracts the caller identity using robust attribute resolution `pid = getattr(participant, "identity", str(participant))` and executes `await task.queue_frames([TTSSpeakFrame(greeting)])`. Queuing a `TTSSpeakFrame` bypasses `OpenAILLMService`, forcing immediate verbal synthesis.
- **Tool Calling Registration**: Tools are registered strictly using Pipecat 1.2.0 signatures `async def _handle_tool(params: FunctionCallParams)`. The handler extracts `params.arguments`, emits data channel packets (`type: "tool_call"` / `"tool_result"`), executes the external tool, and invokes `await params.result_callback(res)`.

---

## 6. Mode 3 Hybrid Runtime (`services/agent-mode3/runtime/session.py`)

Mode 3 is a custom asynchronous loop orchestrator designed for absolute granular control over cognitive ring buffers and interruption mechanics.

```python
async def run_agent_session(session_id: str, room_name: str, agent_token: str): ...
```

### Function Implementation Mechanics
- **Async Ring Buffers (`asyncio.Queue`)**: Audio input from WebRTC tracks is continuously captured into an internal deque. Deepgram STT operates over this buffer in a dedicated background task, firing interim and final transcript callbacks.
- **Cognitive State Loop**: Maintains an explicit state machine (`IDLE`, `LISTENING`, `BUFFERING`, `SYNTHESIZING`, `SPEAKING`). When a final user transcript arrives, the state transitions to `BUFFERING`, dispatching an async streaming completion request to OpenAI.
- **Zero-Latency Interruption Handler**: During assistant audio playback (`SPEAKING`), incoming STT interim frames are continuously evaluated against an acoustic energy threshold. If a valid user barge-in is detected, Mode 3 immediately flushes the internal TTS audio queue, cancels any pending LLM token generators, and transmits an interruption data channel packet to the frontend UI.

---

## 7. Frontend Application UI (`services/frontend/index.html`)

The frontend application is a lightweight, zero-build Vanilla HTML5/CSS3/JS single-page application orchestrating WebRTC connections and real-time timeline visualization.

```javascript
class VoiceApp {
    async connect() { ... }
    disconnect() { ... }
    renderTimeline() { ... }
}
```

### Function Implementation Mechanics
- **`connect()` Handshake**:
  1. Checks `this.state` to prevent double-connect races.
  2. Executes an HTTP POST to `/session/join` with the selected architectural mode.
  3. Initializes `LivekitClient.Room` and connects to `/livekit/` using the returned room name and token.
  4. Initializes a debug WebSocket connection to `/debug/ws` (`event-bridge`).
- **Data Channel & Audio Track Subscription**:
  - Subscribes to room audio tracks and attaches them to an invisible `<audio autoplay>` element.
  - Subscribes to custom data channel messages. When `type: "transcription"` arrives, it dynamically appends interactive chat bubbles (`bg-blue-600` for user, `bg-gray-800` for agent).
- **`renderTimeline()` Component**: Listens for incoming JSON packets from `event-bridge`. For each event, it instantiates a styled DOM card containing the nanosecond timestamp, trace ID, and color-coded event badge (`#4ade80` for success/start, `#eab308` for tool execution, `#f43f5e` for interruptions), appending it instantly to the scrolling metrics timeline.
- **`disconnect()` Teardown**: Performs a rigorous cleanup sequence: disconnects the LiveKit room, stops all local audio tracks, executes `this.debugWs.close()`, and nullifies all socket references (`this.debugWs = null`). This prevents ghost reconnection loops and background resource leaks.

---

## 8. Summary Function Mapping

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        VREP FUNCTION EXECUTION PIPELINE                                │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  [Frontend User Action] ──► VoiceApp.connect()                                         │
│                                │                                                       │
│                                ▼ HTTP POST `/session/join`                             │
│                             SessionRouter.join_session()                               │
│                                │                                                       │
│                                ▼ Container Webhook `/start`                            │
│                             AgentMode2.run_pipecat_session()                           │
│                                │                                                       │
│                                ▼ Room Entry Hook                                       │
│                             on_first_participant_joined()                              │
│                                │                                                       │
│                                ▼ TTSSpeakFrame(greeting)                               │
│                             CartesiaTTSService.process_frame()                         │
│                                │                                                       │
│                                ▼ 24kHz Audio Output Track                              │
│                             LiveKitOutputTransport.send_audio()                        │
│                                │                                                       │
│                                ▼ Redis Telemetry Hook                                  │
│                             EventEmitterProcessor.process_frame()                      │
│                                │                                                       │
│                                ▼ `redis.xadd("telemetry:<id>")`                        │
│                             TelemetryEmitter.emit()                                    │
│                                │                                                       │
│                                ▼ Polling Loop `redis.xread()`                          │
│                             EventBridge.event_stream_endpoint()                        │
│                                │                                                       │
│                                ▼ WebSocket Push `/debug/ws`                            │
│                             VoiceApp.renderTimeline()                                  │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```
