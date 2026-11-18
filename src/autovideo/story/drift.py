"""Catch AI-motion clips whose picture drifts away from the drawn shot (a face turning into someone else).

Run as its own process: python -m autovideo.story.drift <part_dir>
For every clip in jobs_ltx.json that exists, compares CLIP image embeddings of the source drawing with frames
at 25/50/75/100% of the clip. A clip whose worst frame scores below THRESHOLD is deleted (so the next
animate pass, or parallax, redoes that shot) and counted in drift.json."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

MODEL = "openai/clip-vit-large-patch14"
THRESHOLD = 0.85  # part 1 calibration: clean clips scored >= 0.866, the face-morph (18) 0.80 and turn-away (06) 0.79


def frames_at(clip: Path, fractions=(0.25, 0.5, 0.75, 1.0), size=(288, 512)) -> list[Image.Image]:
    """Decode a few frames with ffmpeg (no extra video library)."""
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", str(clip)],
                           capture_output=True, text=True, check=True).stdout.strip() or 0)
    picks = sorted({min(n - 1, max(0, round(f * (n - 1)))) for f in fractions})
    expr = "+".join(f"eq(n\\,{i})" for i in picks)
    w, h = size
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"select='{expr}',scale={w}:{h}",
                          "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    return [Image.fromarray(a) for a in arr]


def scores(model, proc, source: Image.Image, frames: list[Image.Image]) -> list[float]:
    with torch.no_grad():
        inp = proc(images=[source, *frames], return_tensors="pt").to("cuda")
        pooled = model.vision_model(pixel_values=inp["pixel_values"].half()).pooler_output
        emb = model.visual_projection(pooled)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return (emb[1:] @ emb[0]).float().tolist()


def main(part_dir: Path, dry: bool = False):
    jobs = [j for j in json.loads((part_dir / "jobs_ltx.json").read_text()) if Path(j["out"]).exists()]
    if not jobs:
        return
    model = CLIPModel.from_pretrained(MODEL, torch_dtype=torch.float16).to("cuda").eval()
    proc = CLIPProcessor.from_pretrained(MODEL)
    log_path = part_dir / "drift.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else {}
    for j in jobs:
        out = Path(j["out"])
        s = scores(model, proc, Image.open(j["image"]).convert("RGB"), frames_at(out))
        bad = min(s) < THRESHOLD
        entry = log.setdefault(out.name, {"rejected": 0, "scores": []})
        entry["scores"].append([round(x, 3) for x in s])
        print("drift", out.name, "REJECT" if bad else "ok", [round(x, 3) for x in s], flush=True)
        if bad and not dry:
            entry["rejected"] += 1
            out.unlink()
        log_path.write_text(json.dumps(log, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), dry="--dry" in sys.argv)
