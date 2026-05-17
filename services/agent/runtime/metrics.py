import time
import logging
from dataclasses import dataclass

logger = logging.getLogger("uvicorn")

@dataclass
class TurnMetrics:
    turn_id: str
    turn_start_time: float
    stt_final_time: float = 0.0
    llm_first_token_time: float = 0.0
    tts_first_audio_time: float = 0.0

    def record_stt_final(self):
        self.stt_final_time = time.time()

    def record_llm_ttfb(self):
        if self.llm_first_token_time == 0.0:
            self.llm_first_token_time = time.time()
            ttfb_ms = (self.llm_first_token_time - self.stt_final_time) * 1000
            logger.info(f"[METRICS] LLM TTFB for turn {self.turn_id}: {ttfb_ms:.1f}ms")

    def record_tts_ttfb(self):
        if self.tts_first_audio_time == 0.0:
            self.tts_first_audio_time = time.time()
            total_ttfb_ms = (self.tts_first_audio_time - self.stt_final_time) * 1000
            logger.info(f"[METRICS] Speech-to-Ear Total Audio Latency: {total_ttfb_ms:.1f}ms")
