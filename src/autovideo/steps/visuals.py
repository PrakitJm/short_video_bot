import json
import logging
from pathlib import Path

from autovideo import media, subtitles
from autovideo.config import ROOT
from autovideo.providers import Images

log = logging.getLogger("autovideo")
FALLBACK_COLORS = ["0x1e293b", "0x312e81", "0x134e4a", "0x7c2d12", "0x3f3f46"]


def fallback_image(out: Path, text: str, index: int, cfg: dict) -> None:
    """Solid colour with the scene's visual note on top, drawn by libass so Thai marks sit correctly."""
    v = cfg["video"]
    ass = out.with_suffix(".ass")
    lines = [l for _, l in subtitles.split_lines(text, 16)]
    subtitles.write_ass(ass, [(0, 1, r"\N".join(lines))], v["width"], v["height"],
                        subtitles.font_family(ROOT / "assets/fonts"), size=80, align=8)
    color = FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
    media.ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s={v['width']}x{v['height']}:d=1",
                 "-vf", f"subtitles={ass}:fontsdir={ROOT / 'assets/fonts'}", "-frames:v", "1", str(out))
    ass.unlink()


def scene_media(img_dir: Path, scene_id: int) -> Path | None:
    """The scene's clip (mp4) or photo (jpg), whichever the visuals step saved."""
    return next((p for p in (img_dir / f"scene_{scene_id:02d}.mp4", img_dir / f"scene_{scene_id:02d}.jpg")
                 if p.exists()), None)


def run(job_dir: Path, cfg: dict, images: Images) -> dict:
    """images/scene_XX.mp4 (clip) or .jpg (photo or colour card) per scene, plus credits.json."""
    script = json.loads((job_dir / "script.json").read_text(encoding="utf-8"))
    img_dir = job_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    credits_path = job_dir / "credits.json"
    credits = json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.exists() else {}
    excluded_path = job_dir / "excluded_images.json"  # media the owner rejected with "ทำใหม่"
    excluded = set(json.loads(excluded_path.read_text())) if excluded_path.exists() else set()
    tries = [("fetch_video", ".mp4"), ("fetch", ".jpg")] if cfg["images"].get("media") == "video" else [("fetch", ".jpg")]
    tries.append(("fetch", ".jpg", 1))  # last resort: a photo of just the subject (first word of the query)

    for i, scene in enumerate(script["scenes"]):
        key = str(scene["id"])
        if key in credits and scene_media(img_dir, scene["id"]):
            continue
        used = excluded | {c["id"] for c in credits.values() if c}
        credit, out = None, img_dir / f"scene_{scene['id']:02d}.jpg"
        for method, ext, *words in tries:
            out = img_dir / f"scene_{scene['id']:02d}{ext}"
            tmp = out.with_suffix(".tmp" + ext)
            query = " ".join(scene["visual_query"].split()[:words[0]]) if words else scene["visual_query"]
            try:
                credit = getattr(images, method)(query, tmp, used)
            except Exception as e:  # missing media must never sink the job
                log.warning("ซีน %s: %s ไม่สำเร็จ (%s)", key, method, e)
            if credit:
                break
        if credit is None:
            log.warning("ซีน %s: หาภาพไม่ได้ ใช้พื้นหลังสีแทน", key)
            out = img_dir / f"scene_{scene['id']:02d}.jpg"
            tmp = out.with_suffix(".tmp.jpg")
            fallback_image(tmp, scene["visual_note"] or scene["narration"], i, cfg)
        tmp.replace(out)
        credits[key] = credit
        credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=1), encoding="utf-8")
    return credits
