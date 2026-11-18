import json
from fractions import Fraction
from pathlib import Path

from autovideo import media

TELEGRAM_MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit for sendVideo
MAX_SILENCE = 2.0


def check(final: Path, cfg: dict) -> dict:
    v = cfg["video"]
    info = media.probe(final)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    size = final.stat().st_size
    checks = {
        "duration": (v["min_seconds"] <= dur <= v["max_seconds"], f"{dur:.1f} วินาที (ต้อง {v['min_seconds']}–{v['max_seconds']})"),
        "resolution": (bool(video) and (video["width"], video["height"]) == (v["width"], v["height"]),
                       f"{video['width']}x{video['height']}" if video else "ไม่มีภาพ"),
        "fps": (bool(video) and Fraction(video["avg_frame_rate"]) == v["fps"],
                video["avg_frame_rate"] if video else "-"),
        "codec": (bool(video and audio) and video["codec_name"] == "h264" and audio["codec_name"] == "aac",
                  f"{video and video['codec_name']} + {audio and audio['codec_name']}"),
        "audio": (audio is not None, "มีแทร็กเสียง" if audio else "ไม่มีแทร็กเสียง"),
    }
    gaps = media.silences(final, MAX_SILENCE) if audio else []
    checks["silence"] = (not gaps, "ไม่มีช่วงเงียบเกิน 2 วินาที" if not gaps
                         else "เงียบที่ " + ", ".join(f"{s:.1f}s" for s, _ in gaps))
    checks["size"] = (True, f"{size / 1e6:.1f} MB")
    return {
        "passed": all(ok for ok, _ in checks.values()),
        "checks": {k: {"ok": ok, "detail": d} for k, (ok, d) in checks.items()},
    }


def run(job_dir: Path, cfg: dict) -> dict:
    final = job_dir / "final.mp4"
    result = check(final, cfg)
    if final.stat().st_size > TELEGRAM_MAX_BYTES:
        preview = job_dir / "preview.mp4"
        media.ffmpeg("-i", str(final), "-vf", "scale=540:-2", "-c:v", "libx264", "-crf", "30",
                     "-c:a", "aac", "-b:a", "96k", str(preview))
        result["preview"] = preview.name
    (job_dir / "qc.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
