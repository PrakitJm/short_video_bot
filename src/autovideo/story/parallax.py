"""Subtle 2.5D motion: estimate depth once, then drift the camera so near things move more than far ones.

Run as its own process: python -m autovideo.story.parallax <part_dir>
Reads <part_dir>/jobs_parallax.json [{image, out, seconds, seed}]."""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import pipeline

DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"  # Apache-2.0


def depth_map(estimator, img: Image.Image, size: tuple[int, int]) -> np.ndarray:
    d = np.asarray(estimator(img)["depth"], dtype=np.float32)
    d = cv2.resize(d, size, interpolation=cv2.INTER_CUBIC)
    d = (d - d.min()) / max(float(d.max() - d.min()), 1e-6)  # 1 = near
    return cv2.GaussianBlur(d, (0, 0), 8)  # soft edges so the warp doesn't tear outlines


def render(img: np.ndarray, depth: np.ndarray, out: Path, seconds: float, fps: int, seed: int,
           w: int, h: int, shift: float = 28, zoom: float = 0.05) -> None:
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0, 2 * np.pi)  # each shot drifts in its own direction
    dx, dy = np.cos(angle) * shift, np.sin(angle) * shift * 0.5
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    frames = max(int(round(seconds * fps)), 1)
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                           "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    for f in range(frames):
        t = f / max(frames - 1, 1)
        ease = 0.5 - 0.5 * np.cos(np.pi * t)  # slow in, slow out
        s = 1 + zoom * (0.5 + ease)  # always zoomed a little so edges never show
        off = (ease - 0.5) * 2
        mx = cx + (xs - cx) / s - dx * off * depth
        my = cy + (ys - cy) / s - dy * off * depth
        ff.stdin.write(cv2.remap(img, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT).tobytes())
    ff.stdin.close()
    if ff.wait():
        raise RuntimeError(f"ffmpeg failed on {out}")


def main(part_dir: Path, w: int = 1080, h: int = 1920, fps: int = 30):
    jobs = [j for j in json.loads((part_dir / "jobs_parallax.json").read_text()) if not Path(j["out"]).exists()]
    if not jobs:
        return
    estimator = pipeline("depth-estimation", model=DEPTH_MODEL, device=0 if torch.cuda.is_available() else -1)
    for j in jobs:
        img = Image.open(j["image"]).convert("RGB").resize((w, h), Image.LANCZOS)
        tmp = Path(j["out"]).with_suffix(".tmp.mp4")
        render(np.asarray(img), depth_map(estimator, img, (w, h)), tmp, j["seconds"], fps, j["seed"], w, h)
        tmp.replace(j["out"])
        print("parallax", j["out"], flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
