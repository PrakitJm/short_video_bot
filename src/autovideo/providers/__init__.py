"""Provider interfaces. Each pipeline step depends only on these, never on a concrete service."""
import logging
import os
from pathlib import Path
from typing import Protocol


class LLM(Protocol):
    def generate_json(self, system: str, prompt: str, schema: dict) -> str:
        """Return the model's raw JSON text."""


class TTS(Protocol):
    def synthesize(self, text: str, out: Path) -> list[dict]:
        """Write speech to `out` (mp3); return words as {text, start, end} in seconds."""


class Images(Protocol):
    def fetch(self, query: str, out: Path, exclude: set[str]) -> dict | None:
        """Save a portrait photo to `out` (jpg), skipping ids in `exclude`.
        Return its credit {id, photographer, url}, or None when nothing fits."""

    def fetch_video(self, query: str, out: Path, exclude: set[str]) -> dict | None:
        """Same as fetch, but a short mp4 clip."""


class Uploader(Protocol):
    def upload(self, video: Path, meta: dict) -> str:
        """Upload with YouTube-style {snippet, status} metadata; return the video id."""


def get_llm(cfg: dict, dry_run: bool = False) -> LLM:
    if dry_run:
        from autovideo.providers.fakes import FakeLLM
        return FakeLLM()
    llm = cfg["llm"]
    if llm["provider"] == "gemini":
        from autovideo.providers.llm_gemini import GeminiLLM
        return GeminiLLM(model=llm["model"], max_retries=cfg["limits"]["max_retries"])
    raise ValueError(f"ไม่รู้จัก llm.provider: {llm['provider']}")


def get_tts(cfg: dict, dry_run: bool = False) -> TTS:
    if dry_run:
        from autovideo.providers.fakes import FakeTTS
        return FakeTTS()
    tts = cfg["tts"]
    if tts["provider"] == "edge":
        from autovideo.providers.tts_edge import EdgeTTS
        return EdgeTTS(voice=tts["voice"], rate=tts["rate"])
    raise ValueError(f"ไม่รู้จัก tts.provider: {tts['provider']}")


def get_images(cfg: dict, dry_run: bool = False) -> Images:
    from autovideo.providers.fakes import FakeImages
    if dry_run:
        return FakeImages()
    if cfg["images"]["provider"] == "pixabay":
        if not os.getenv("PIXABAY_API_KEY"):
            logging.getLogger("autovideo").warning("ยังไม่มี PIXABAY_API_KEY ใช้พื้นหลังสีแทนภาพทุกซีน")
            return FakeImages()
        from autovideo.providers.images_pixabay import PixabayImages
        return PixabayImages()
    raise ValueError(f"ไม่รู้จัก images.provider: {cfg['images']['provider']}")


def get_uploader(dry_run: bool = False) -> Uploader:
    if dry_run:
        from autovideo.providers.fakes import FakeUploader
        return FakeUploader()
    from autovideo.providers.upload_youtube import YouTubeUploader
    return YouTubeUploader()
