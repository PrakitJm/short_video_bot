import json
from pathlib import Path

from autovideo.providers import Uploader


def build_meta(script: dict, credits: dict, cfg: dict, music_credit: str | None = None) -> dict:
    yt = cfg["youtube"]
    people = {(c["photographer"], c["url"]) for c in credits.values() if c}
    desc = script["description"]
    if people:
        desc += "\n\nภาพ/วิดีโอจาก Pixabay:\n" + "\n".join(f"- {name} {url}" for name, url in sorted(people))
    if music_credit:  # CC BY requires this line
        desc += f"\n\nเพลง: {music_credit}"
    status = {"privacyStatus": yt["privacy"], "selfDeclaredMadeForKids": yt["made_for_kids"]}
    if yt["mark_synthetic"]:
        status["containsSyntheticMedia"] = True
    return {
        "snippet": {
            "title": script["title"][:100],
            "description": desc[:5000],
            "tags": script["tags"],
            "categoryId": script.get("category_id", yt["category_id"]),
            "defaultLanguage": cfg["channel"]["language"],
        },
        "status": status,
    }


def run(job_dir: Path, cfg: dict, uploader: Uploader) -> str:
    done = job_dir / "youtube.json"
    if done.exists():  # never upload the same job twice
        return json.loads(done.read_text())["video_id"]
    script = json.loads((job_dir / "script.json").read_text(encoding="utf-8"))
    credits_path = job_dir / "credits.json"
    credits = json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.exists() else {}
    music_path = job_dir / "music.json"
    music = json.loads(music_path.read_text(encoding="utf-8")) if music_path.exists() else {}
    video_id = uploader.upload(job_dir / "final.mp4", build_meta(script, credits, cfg, music.get("credit")))
    done.write_text(json.dumps({"video_id": video_id}))
    return video_id


def studio_link(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/edit"
