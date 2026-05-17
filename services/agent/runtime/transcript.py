class TranscriptAggregator:
    def __init__(self):
        self.partial = ""
        self.final_segments: list[str] = []

    def on_partial(self, text: str):
        self.partial = text

    def on_final(self, text: str):
        self.final_segments.append(text)
        self.partial = ""

    def has_unflushed_finals(self) -> bool:
        return len(self.final_segments) > 0

    def flush(self) -> str:
        full = " ".join(self.final_segments).strip()
        self.final_segments = []
        self.partial = ""
        return full
