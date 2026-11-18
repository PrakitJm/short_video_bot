"""Load config.yaml and .env from the project root (current working directory)."""
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path.cwd()
SECRET_KEYS = [
    "GEMINI_API_KEY",
    "PIXABAY_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_CHAT_ID",
    "YOUTUBE_CLIENT_SECRETS_FILE",
]


def load_config(path: Path = ROOT / "config.yaml") -> dict:
    load_dotenv(ROOT / ".env")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
