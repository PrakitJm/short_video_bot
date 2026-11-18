"""Thin wrappers around the FFmpeg command-line tools."""
import json
import re
import shutil
import subprocess
from pathlib import Path


def _need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise RuntimeError(f"ไม่พบโปรแกรม {tool} ติดตั้ง FFmpeg ก่อน (ดู README)")
    return path


def duration(path: Path) -> float:
    out = subprocess.run(
        [_need("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def tone(path: Path, seconds: float) -> None:
    """A quiet beep standing in for speech (fakes and tests)."""
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000", "-t", f"{seconds:.2f}",
           "-af", "volume=0.3", "-c:a", "libmp3lame", str(path))


def ffmpeg(*args: str) -> None:
    r = subprocess.run([_need("ffmpeg"), "-y", "-hide_banner", "-v", "error", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg ล้มเหลว: {r.stderr.strip()[-800:]}")


def probe(path: Path) -> dict:
    out = subprocess.run(
        [_need("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def silences(path: Path, min_seconds: float, noise_db: int = -40) -> list[tuple[float, float]]:
    """(start, end) of every stretch quieter than noise_db lasting at least min_seconds."""
    r = subprocess.run(
        [_need("ffmpeg"), "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_seconds}",
         "-vn", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(starts, ends + [float("inf")] * (len(starts) - len(ends))))
