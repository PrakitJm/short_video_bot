import asyncio
from pathlib import Path

import edge_tts

TICKS = 10_000_000  # edge-tts offsets are in 100-nanosecond units


class EdgeTTS:
    def __init__(self, voice: str, rate: str = "+0%"):
        if not voice:
            raise ValueError("ยังไม่ได้ตั้งค่า tts.voice ใน config.yaml")
        self.voice = voice
        self.rate = rate

    def synthesize(self, text: str, out: Path) -> list[dict]:
        try:
            return asyncio.run(self._run(text, out))
        except edge_tts.exceptions.EdgeTTSException as e:
            raise RuntimeError(f"edge-tts ใช้ไม่ได้ (เสียง {self.voice}): {type(e).__name__} {e}") from e

    async def _run(self, text: str, out: Path) -> list[dict]:
        comm = edge_tts.Communicate(text, self.voice, rate=self.rate, boundary="WordBoundary")
        words, audio = [], bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS
                words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / TICKS})
        out.write_bytes(audio)
        return words
