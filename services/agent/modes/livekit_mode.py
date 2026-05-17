import asyncio
import json
import logging
from livekit import rtc
from livekit.rtc import AudioStream
from config import settings

logger = logging.getLogger("uvicorn")

async def handle_audio_track(track: rtc.RemoteAudioTrack):
    stream = AudioStream(track)
    try:
        async for event in stream:
            frame = event.frame
            logger.info(f"audio frame samples={frame.samples_per_channel}")
    finally:
        await stream.aclose()

async def run_session(session_id: str, room_name: str, agent_token: str):
    logger.info(f"[LIVEKIT MODE - PHASE1] session={session_id} room={room_name}")
    room = rtc.Room()

    @room.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.create_task(handle_audio_track(track))

    await room.connect(settings.livekit_url, agent_token)
    try:
        await room.local_participant.publish_data(
            json.dumps({"type": "mode_info", "mode": "livekit", "phase": 1}).encode()
        )
        while True:
            await asyncio.sleep(1)
            if len(room.remote_participants) == 0: break
    finally:
        await room.disconnect()
