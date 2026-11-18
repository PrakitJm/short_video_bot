"""Offline stand-ins for every provider, used by tests and --dry-run."""
import json
from pathlib import Path

from autovideo import media


def sample_script(topic: str = "ทดสอบระบบ") -> dict:
    return {
        "topic": topic,
        "title": f"เรื่องน่ารู้: {topic}",
        "description": "คลิปทดสอบจากโหมด dry-run",
        "tags": ["ทดสอบ"],
        "scenes": [
            {"id": i, "narration": f"นี่คือบทพากย์ของซีนที่ {i}", "visual_query": "city skyline", "visual_note": "ภาพเมือง"}
            for i in range(1, 6)
        ],
    }


class FakeLLM:
    def __init__(self, responses: list[str] | None = None):
        self.responses = responses
        self.calls: list[str] = []

    def generate_json(self, system: str, prompt: str, schema: dict) -> str:
        self.calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return json.dumps(sample_script(), ensure_ascii=False)


class FakeTTS:
    """A beep; pretends every 4 characters is a 1 s word (5 sample scenes come to ~30 s)."""

    def synthesize(self, text: str, out: Path) -> list[dict]:
        chunks = [text[i:i + 4] for i in range(0, len(text), 4)]
        media.tone(out, len(chunks))
        return [{"text": c, "start": float(i), "end": i + 1.0} for i, c in enumerate(chunks)]


class FakeImages:
    """Never finds a photo, so the visuals step exercises its colour fallback."""

    def fetch(self, query: str, out: Path, exclude: set[str]) -> dict | None:
        return None

    def fetch_video(self, query: str, out: Path, exclude: set[str]) -> dict | None:
        return None


class FakeUploader:
    def __init__(self):
        self.uploads: list[dict] = []

    def upload(self, video: Path, meta: dict) -> str:
        self.uploads.append(meta)
        return f"dryrun{len(self.uploads)}"
