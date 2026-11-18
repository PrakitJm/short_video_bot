import json
import random
from pathlib import Path

from autovideo import media
from autovideo.config import ROOT
from autovideo.steps.visuals import scene_media


def scene_frames(durations: list[float], fps: int) -> list[int]:
    """Frames per scene, rounded on cumulative time so the video never drifts from the audio."""
    edges, t = [0], 0.0
    for d in durations:
        t += d
        edges.append(round(t * fps))
    return [b - a for a, b in zip(edges, edges[1:])]


def pick_music(job_dir: Path) -> Path | None:
    """A random track from assets/music per job, remembered in music.json so resumes and credits agree."""
    saved = job_dir / "music.json"
    if saved.exists():
        name = json.loads(saved.read_text(encoding="utf-8"))["file"]
        return ROOT / "assets/music" / name if name else None
    tracks = sorted((ROOT / "assets/music").glob("*.mp3"))
    track = random.choice(tracks) if tracks else None
    credits_path = ROOT / "assets/music/credits.json"
    credits = json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.exists() else {}
    name = track.name if track else None
    saved.write_text(json.dumps({"file": name, "credit": credits.get(name)}, ensure_ascii=False), encoding="utf-8")
    return track


def render_clip(src: Path, out: Path, frames: int, cfg: dict) -> None:
    """Stock video: centre-crop to portrait, loop if shorter than the scene, drop its own audio."""
    v = cfg["video"]
    w, h, fps = v["width"], v["height"], v["fps"]
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1,format=yuv420p"
    tmp = out.with_suffix(".tmp.mp4")
    media.ffmpeg("-stream_loop", "-1", "-i", str(src), "-vf", vf, "-frames:v", str(frames), "-an",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(tmp))
    tmp.replace(out)


def render_scene(img: Path, out: Path, frames: int, cfg: dict, zoom_in: bool) -> None:
    v = cfg["video"]
    w, h, fps = v["width"], v["height"], v["fps"]
    # Upscale 2x before zoompan: zoompan rounds to whole pixels, which jitters at output size.
    step = 0.12 / max(frames, 1)
    z = f"1+{step}*on" if zoom_in else f"1.12-{step}*on"
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps},"
          f"format=yuv420p")
    tmp = out.with_suffix(".tmp.mp4")
    media.ffmpeg("-i", str(img), "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "18", str(tmp))
    tmp.replace(out)


def run(job_dir: Path, cfg: dict) -> Path:
    final = job_dir / "final.mp4"
    if final.exists():
        return final
    script = json.loads((job_dir / "script.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in script["scenes"]]
    metas = [json.loads((job_dir / f"audio/scene_{i:02d}.words.json").read_text(encoding="utf-8")) for i in ids]
    frames = scene_frames([m["duration"] for m in metas], cfg["video"]["fps"])

    work = job_dir / "render"
    work.mkdir(exist_ok=True)
    for n, (i, f) in enumerate(zip(ids, frames)):
        clip = work / f"scene_{i:02d}.mp4"
        if not clip.exists():
            src = scene_media(job_dir / "images", i)
            if src.suffix == ".mp4":
                render_clip(src, clip, f, cfg)
            else:
                render_scene(src, clip, f, cfg, zoom_in=n % 2 == 0)

    (work / "video.txt").write_text("".join(f"file 'scene_{i:02d}.mp4'\n" for i in ids))
    (work / "audio.txt").write_text("".join(f"file '../audio/scene_{i:02d}.mp3'\n" for i in ids))
    fonts = ROOT / "assets/fonts"
    inputs = ["-f", "concat", "-safe", "0", "-i", str(work / "video.txt"),
              "-f", "concat", "-safe", "0", "-i", str(work / "audio.txt")]
    audio = "[1:a]aresample=48000[a]"
    total = sum(frames) / cfg["video"]["fps"]
    track = pick_music(job_dir)
    if track:
        vol = cfg.get("music", {}).get("volume", 0.12)
        inputs += ["-stream_loop", "-1", "-i", str(track)]
        audio = (f"[1:a]aresample=48000[voice];[2:a]aresample=48000,volume={vol},"
                 f"afade=t=out:st={max(total - 1.5, 0):.3f}:d=1.5[bg];"
                 "[voice][bg]amix=inputs=2:duration=first:normalize=0[a]")
    tmp = job_dir / "final.tmp.mp4"
    media.ffmpeg(*inputs,
                 "-filter_complex", f"[0:v]subtitles={job_dir / 'subs.ass'}:fontsdir={fonts}[v];{audio}",
                 "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-r", str(cfg["video"]["fps"]), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                 str(tmp))
    tmp.replace(final)
    return final
