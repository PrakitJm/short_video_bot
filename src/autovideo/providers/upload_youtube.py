import os
from pathlib import Path

from autovideo.config import ROOT

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN = ROOT / "data/youtube_token.json"


def authorize() -> Path:
    """One-time browser login; stores a refresh token for later unattended uploads."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    secrets = ROOT / (os.getenv("YOUTUBE_CLIENT_SECRETS_FILE") or "client_secret.json")
    if not secrets.exists():
        raise ValueError(f"ไม่พบไฟล์ {secrets.name} (OAuth client แบบ Desktop จาก Google Cloud)")
    # open_browser=False: under WSL there's no browser; the owner opens the printed URL in Windows.
    creds = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES).run_local_server(
        port=8765, open_browser=False, authorization_prompt_message="เปิดลิงก์นี้ในเบราว์เซอร์แล้วกดอนุญาต:\n{url}")
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(creds.to_json())
    return TOKEN


class YouTubeUploader:
    def upload(self, video: Path, meta: dict) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        if not TOKEN.exists():
            raise ValueError("ยังไม่ได้เชื่อม YouTube รัน: uv run autovideo auth youtube")
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        if not creds.valid:
            from google.auth.exceptions import RefreshError
            try:
                creds.refresh(Request())
            except RefreshError as e:  # Testing-mode OAuth apps lose their refresh token after 7 days
                raise ValueError("การเชื่อม YouTube หมดอายุ (แอปโหมด Testing หมดทุก 7 วัน) "
                                 "รันบนคอม: uv run autovideo auth youtube แล้วสั่ง /retry <เลขงาน>") from e
            TOKEN.write_text(creds.to_json())
        yt = build("youtube", "v3", credentials=creds)
        req = yt.videos().insert(
            part="snippet,status",
            body=meta,
            media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True),
        )
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
        return resp["id"]
