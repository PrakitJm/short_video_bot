"""Pick the best take of every shot without a human: CLIP similarity between each take and its prompt.

Run as its own process: python -m autovideo.story.pick <part_dir>
Writes shots/shot_XX.png (the winner) and picks.json. A shot_XX.png that already exists is kept, so a
take chosen by hand (copy shot_XX.cN.png over shot_XX.png) is never overridden."""
import json
import shutil
import sys
from pathlib import Path

import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

MODEL = "openai/clip-vit-large-patch14"  # MIT


def readable(p: Path) -> bool:
    """False for missing or half-written files (a hard WSL shutdown can leave a truncated PNG)."""
    try:
        with Image.open(p) as im:
            im.verify()
        return True
    except (OSError, SyntaxError):
        return False


def main(part_dir: Path):
    spec = json.loads((part_dir / "jobs_sdxl.json").read_text())
    todo = [j for j in spec["jobs"] if not Path(j["out"]).exists()]
    if not todo:
        return
    model = CLIPModel.from_pretrained(MODEL, torch_dtype=torch.float16).to("cuda").eval()
    proc = CLIPProcessor.from_pretrained(MODEL)
    picks_path = part_dir / "picks.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    for j in todo:
        out = Path(j["out"])
        takes = [out.with_suffix(f".c{k}.png") for k in range(j.get("candidates", 1))]
        takes = [t for t in takes if readable(t)]
        if not takes:
            raise RuntimeError(f"{out.name}: ไม่มีภาพที่เปิดได้เลย")
        # Score against what the shot should show; the style/quality tags (last piece) say nothing about content.
        pieces = j["prompt"] if isinstance(j["prompt"], list) else [j["prompt"]]
        text = ", ".join(pieces[:-1] or pieces)
        with torch.no_grad():
            inp = proc(text=[text], images=[Image.open(t).convert("RGB") for t in takes], return_tensors="pt",
                       padding=True, truncation=True, max_length=77).to("cuda")
            scores = model(**{k: (v.half() if v.is_floating_point() else v) for k, v in inp.items()}).logits_per_image
        scores = scores[:, 0].float().tolist()
        best = max(range(len(takes)), key=scores.__getitem__)
        shutil.copy(takes[best], out)
        picks[out.name] = {"take": best, "scores": [round(s, 2) for s in scores]}
        print("picked", out.name, best, picks[out.name]["scores"], flush=True)
        picks_path.write_text(json.dumps(picks, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
