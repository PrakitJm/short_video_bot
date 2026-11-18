"""Gemini looks at the takes of each shot next to its narration and picks the one that tells the story.

CLIP only compares an image with the drawing prompt; Gemini reads the Thai narration, so it notices "three
slimes when the story has one" or "a sunny forest in a night scene". For every shot it also writes:
  - a better drawing prompt when no take matches (the shot is then redrawn once with it), and
  - a motion prompt for that shot ("the slime hops toward the camera, the boy flinches"), used by LTX.
Results go to judge.json; the chosen take is copied to shots/shot_XX.png. Any API failure (quota, network)
leaves the shot to the CLIP picker, so the video is still made."""
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("autovideo")
GOOD_MATCH = 6  # 0-10: below this no take tells the story well enough
SCHEMA = {
    "type": "object",
    "properties": {
        "images": {"type": "array", "items": {"type": "object", "properties": {
            "match": {"type": "integer"}, "quality": {"type": "integer"}, "problem": {"type": "string"}},
            "required": ["match", "quality", "problem"]}},
        "better_prompt": {"type": "string"},
        "motion": {"type": "string"},
    },
    "required": ["images", "better_prompt", "motion"],
}
PROMPT = """You review storyboard frames for an anime short video. The frames are in order.
Narration of this shot (Thai): {narration}
What the frame should show: {image_prompt}
Characters that should appear: {chars}
For each frame give:
- match 0-10: does it clearly show what the narration describes (right subject, action, count, time of day, place)?
- quality 0-10: anatomy, face, hands, proportions, no artifacts or extra limbs.
- problem: one short sentence about what is wrong.
Then write:
- better_prompt: an improved English prompt for an anime image model (Animagine XL) for this shot: danbooru-style tags
  first (e.g. "1boy, solo, sitting, night, forest"), then a short scene description; describe only ONE main
  character's pose and action; no character names; max 40 words.
- motion: one English sentence describing natural, gentle movement for a 3-second animated clip of this shot that fits
  the narration (what moves: hair, eyes, mouth, hands, creatures, lights, particles; plus a slow camera move).
  Keep the subject in place; no new objects; no scene change."""


def client():
    from google import genai
    key = os.getenv("GEMINI_API_KEY")
    return genai.Client(api_key=key) if key else None


def review(gc, model: str, takes: list[Path], shot: dict, chars: str) -> dict:
    from google.genai import types
    parts = [types.Part.from_bytes(data=t.read_bytes(), mime_type="image/png") for t in takes]
    text = PROMPT.format(narration=shot["narration"], image_prompt=shot["image_prompt"], chars=chars or "none")
    for attempt in range(3):
        try:
            r = gc.models.generate_content(model=model, contents=[*parts, text], config=types.GenerateContentConfig(
                response_mime_type="application/json", response_json_schema=SCHEMA))
            out = json.loads(r.text)
            if len(out["images"]) == len(takes):
                return out
        except Exception as e:  # noqa: BLE001 - quota/network/parse: retry, then give up on this shot
            if getattr(e, "code", None) == 429:
                raise
            log.warning("judge %s attempt %s: %s", shot["id"], attempt + 1, e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("Gemini judge gave no usable answer")


def score(im: dict) -> float:
    return im["match"] * 0.65 + im["quality"] * 0.35


# Free-tier quota is per model per day (20 requests on gemini-3.6-flash), so the judge walks through several
# models and leaves the script model (llm.model) for last.
JUDGE_MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]


def run(d: Path, shots: list[dict], story: dict, cfg: dict, candidates: int, final: bool) -> list[dict]:
    """Judge every shot that has no chosen take yet. Returns shots that need a redraw (only when not final)."""
    gc = client()
    if gc is None:
        return []
    models = list(cfg.get("story", {}).get("judge_models") or JUDGE_MODELS)
    path = d / "judge.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    redo = []
    for s in shots:
        out = d / "shots" / f"shot_{s['id']:02d}.png"
        if out.exists():
            continue
        takes = [t for k in range(candidates) if (t := out.with_suffix(f".c{k}.png")).exists()]
        if not takes:
            continue
        chars = ", ".join(story["characters"][c]["tag"] for c in s["characters"])
        res = None
        while models and res is None:
            try:
                res = review(gc, models[0], takes, s, chars)
            except Exception as e:  # noqa: BLE001 - quota: next model; anything else: leave the rest to CLIP
                if getattr(e, "code", None) == 429:
                    log.warning("judge: %s quota used up for today, trying the next model", models.pop(0))
                    continue
                log.warning("Gemini judge failed at shot %s (%s)", s["id"], e)
                break
        if res is None:
            log.warning("Gemini judge stopped at shot %s; CLIP picks the rest", s["id"])
            break
        best = max(range(len(takes)), key=lambda k: score(res["images"][k]))
        res["best"], res["takes"] = best, [t.name for t in takes]
        results[out.name] = res
        path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        if res["images"][best]["match"] < GOOD_MATCH and not final:
            redo.append({**s, "image_prompt": res["better_prompt"]})
            log.info("judge shot %s: no take matches (best %s/10), redraw with: %s",
                     s["id"], res["images"][best]["match"], res["better_prompt"])
            continue
        import shutil
        shutil.copy(takes[best], out)
        log.info("judge shot %s: take %s (match %s, quality %s)", s["id"], best,
                 res["images"][best]["match"], res["images"][best]["quality"])
    return redo


def motion(d: Path, shot_id: int) -> str | None:
    p = d / "judge.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8")).get(f"shot_{shot_id:02d}.png", {}).get("motion")
