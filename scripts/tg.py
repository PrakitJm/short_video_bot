"""Send a message (or a video) to the owner on Telegram, using TELEGRAM_* from .env.
  uv run python scripts/tg.py "text"            uv run python scripts/tg.py "caption" --video path.mp4"""
import argparse
import json
import os
import uuid
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
API = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
CHAT = os.environ["TELEGRAM_OWNER_CHAT_ID"]


def send(text: str, video: str | None = None) -> dict:
    if not video:
        data = json.dumps({"chat_id": CHAT, "text": text}).encode()
        req = urllib.request.Request(f"{API}/sendMessage", data, {"Content-Type": "application/json"})
    else:  # multipart upload, no extra dependency
        b = uuid.uuid4().hex
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                 for k, v in (("chat_id", CHAT), ("caption", text[:1000]), ("supports_streaming", "true"))]
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="video"; filename="{Path(video).name}"\r\n'
                     f"Content-Type: video/mp4\r\n\r\n".encode() + Path(video).read_bytes() + b"\r\n")
        req = urllib.request.Request(f"{API}/sendVideo", b"".join(parts) + f"--{b}--\r\n".encode(),
                                     {"Content-Type": f"multipart/form-data; boundary={b}"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("text")
    p.add_argument("--video")
    a = p.parse_args()
    print("ok" if send(a.text, a.video).get("ok") else "failed")
