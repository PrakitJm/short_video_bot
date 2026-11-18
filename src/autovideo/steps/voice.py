import json
from pathlib import Path

from autovideo import media, subtitles
from autovideo.config import ROOT
from autovideo.providers import TTS


def run(job_dir: Path, cfg: dict, tts: TTS) -> list[dict]:
    """Per scene: audio/scene_XX.mp3 + scene_XX.words.json ({duration, words}). Then subs.ass for the whole clip."""
    script = json.loads((job_dir / "script.json").read_text(encoding="utf-8"))
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    scenes = []
    for scene in script["scenes"]:
        mp3 = audio_dir / f"scene_{scene['id']:02d}.mp3"
        meta_path = audio_dir / f"scene_{scene['id']:02d}.words.json"
        if meta_path.exists() and mp3.exists():
            scenes.append(json.loads(meta_path.read_text(encoding="utf-8")))
            continue
        tmp = mp3.with_suffix(".tmp.mp3")
        words = tts.synthesize(scene["narration"], tmp)
        meta = {"id": scene["id"], "duration": media.duration(tmp), "words": words}
        tmp.replace(mp3)
        # words.json is written last, so its presence marks a finished scene.
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        scenes.append(meta)

    total = sum(s["duration"] for s in scenes)
    limit = cfg["video"]["max_seconds"]
    if total > limit:
        raise RuntimeError(f"เสียงพากย์รวมยาว {total:.1f} วินาที เกิน video.max_seconds ({limit}) ให้เขียนบทให้สั้นลง")

    events, offset = [], 0.0
    for scene, meta in zip(script["scenes"], scenes):
        for s, e, line in subtitles.timed_lines(scene["narration"], meta["words"], meta["duration"]):
            events.append((offset + s, offset + e, line))
        offset += meta["duration"]
    v = cfg["video"]
    subtitles.write_ass(job_dir / "subs.ass", events, v["width"], v["height"], subtitles.font_family(ROOT / "assets/fonts"))
    return scenes
