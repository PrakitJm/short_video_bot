"""Make one part of a story series into a finished, QC'd video.

voice (edge-tts) -> draw takes (SDXL) -> pick best take (CLIP) -> motion (LTX for `motion: ai` shots,
2.5D parallax for the rest) -> render -> QC.
Every step skips work already on disk, so a crash or Ctrl-C just resumes. GPU steps run as child
processes so each model's memory is returned before the next one loads."""
import copy
import json
import logging
import os
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

from autovideo import db
from autovideo.providers import get_tts
from autovideo.steps import qc, render, voice

log = logging.getLogger("autovideo")
MEMORY_MAX = "5G"  # WSL has ~7.6 GB; leave room for the shell, editor and Claude Code


def gpu_step(module: str, *args: str, env: dict) -> None:
    log.info("▶ %s %s", module, " ".join(args[:-1]))
    cmd = [sys.executable, "-m", f"autovideo.story.{module}", *args]
    if shutil.which("systemd-run"):  # hard RAM cap: going over kills only this step, never the whole WSL
        cmd = ["systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={MEMORY_MAX}",
               "-p", "MemorySwapMax=1G", *cmd]
    # oom_score_adj 1000: if RAM still runs out, the kernel picks this child first.
    r = subprocess.run(cmd, env=env, preexec_fn=lambda: Path("/proc/self/oom_score_adj").write_text("1000"))
    if r.returncode:
        raise RuntimeError(f"{module} {' '.join(args[:-1])} ล้มเหลว (exit {r.returncode})")


def part_script(story: dict, part: dict) -> dict:
    """The part as a normal script.json, so the existing voice/render/qc/publish steps just work."""
    n = max(p["part"] for p in story["parts"] + story.get("outline", []))
    return {
        "topic": f"{story['series']} ตอนที่ {part['part']}",
        "title": f"{story['series']} ตอนที่ {part['part']}/{n}: {part['title']}"[:70],
        "description": f"{story['series']} ตอนที่ {part['part']} จาก {n} ตอน\nภาพ การเคลื่อนไหว และเสียงพากย์สร้างด้วย AI",
        "tags": story.get("tags", ["นิทาน", "เรื่องเล่า", story["series"]]),
        "category_id": story.get("category_id", "24"),  # Entertainment
        "scenes": [{"id": s["id"], "narration": s["narration"], "visual_query": "story", "visual_note": ""}
                   for s in part["shots"]],
    }


def run(story_path: Path, part_no: int, cfg: dict, draw_only: bool = False, out_dir: Path | None = None,
        seed_offset: int = 0, check: bool = True) -> Path:
    """seed_offset changes every drawing (used by "ทำใหม่"); check=False leaves QC to the orchestrator."""
    story = json.loads(story_path.read_text(encoding="utf-8"))
    part = next((p for p in story["parts"] if p["part"] == part_no), None)
    if part is None:
        raise ValueError(f"{story_path.name} ยังไม่มีบทตอนที่ {part_no}")
    d = out_dir or db.JOBS_DIR.parent / "stories" / story_path.stem / f"part{part_no}"
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "shots").mkdir(exist_ok=True)
    sc = cfg["story"]
    cfg = copy.deepcopy(cfg)
    cfg["video"]["max_seconds"] = sc["max_seconds"]
    env = {**os.environ, "HF_HOME": sc["models_dir"], "HF_HUB_OFFLINE": "1"}

    script = d / "script.json"
    if not script.exists():
        script.write_text(json.dumps(part_script(story, part), ensure_ascii=False, indent=1), encoding="utf-8")
    voice.run(d, cfg, get_tts(cfg))
    seconds = {s["id"]: json.loads((d / f"audio/scene_{s['id']:02d}.words.json").read_text())["duration"]
               for s in part["shots"]}

    def shot(s):
        return d / "shots" / f"shot_{s['id']:02d}.png"

    def clip(s):
        return d / "images" / f"scene_{s['id']:02d}.mp4"

    def seed(s):
        return zlib.crc32(f"{story_path.stem}/{part_no}/{s['id']}".encode()) + seed_offset

    def motion_of(s):  # the judge's shot-specific motion, else a generic gentle one
        from autovideo.story.judge import motion
        return motion(d, s["id"]) or (f"{s['image_prompt']}. Natural small movements: breathing, blinking, hair and "
                                      "clothes moving in the wind, light flickering, slow camera push-in.")

    def looks(s):
        return ", ".join(story["characters"][c]["tag"] for c in s["characters"])

    # Prompt pieces in priority order; the drawer keeps as many as fit in CLIP's 77 tokens. Only the main
    # character's look is added: SDXL mixes up attributes when two people are described.
    cand = sc.get("candidates", 1)

    def draw_jobs(shots, n, offset=0):
        return [{"out": str(shot(s)), "seed": seed(s) + offset, "candidates": n,
                 "prompt": [*(story["characters"][c]["tag"] for c in s["characters"][:1]), s["image_prompt"],
                            story["style"]]} for s in shots]

    def write_draw_jobs(jobs):
        (d / "jobs_sdxl.json").write_text(json.dumps({"model": sc.get("image_model", {}), "jobs": jobs},
                                                     ensure_ascii=False, indent=1))

    write_draw_jobs(draw_jobs(part["shots"], cand))
    gpu_step("sdxl", str(d), env=env)
    if draw_only:
        return d / "shots"
    if sc.get("judge") == "gemini":
        # Gemini reads the narration and picks the take that tells the story; shots with no good take are
        # redrawn once with its better prompt (extra takes c3..), then judged again over all takes.
        from autovideo.story import judge
        redo = judge.run(d, part["shots"], story, cfg, cand, final=False)
        if redo:
            ids = {s["id"] for s in redo}
            write_draw_jobs([j for j in draw_jobs(part["shots"], cand) if int(Path(j["out"]).stem[-2:]) not in ids]
                            + draw_jobs(redo, 2 * cand, offset=500))
            gpu_step("sdxl", str(d), env=env)
            judge.run(d, redo, story, cfg, 2 * cand, final=True)
    gpu_step("pick", str(d), env=env)  # CLIP picks whatever the judge did not (no key, quota, errors)

    # story.ai_all: every shot gets AI motion (keyframe-locked loops); otherwise only shots marked motion: ai.
    ai = part["shots"] if sc.get("ai_all") else [s for s in part["shots"] if s.get("motion") == "ai"]
    if ai and sc.get("ai_motion", True):
        drift_log = d / "drift.json"
        for attempt in range(2):  # a clip that drifts away from the drawing is redone once with a new seed
            tries = json.loads(drift_log.read_text()) if drift_log.exists() else {}
            (d / "jobs_ltx.json").write_text(json.dumps([
                {"image": str(shot(s)), "out": str(clip(s)), "seconds": seconds[s["id"]] + 0.2,
                 "seed": seed(s) + 7919 * tries.get(clip(s).name, {}).get("rejected", 0),
                 "prompt": f"{motion_of(s)} {looks(s)}. {story['style']}"}
                for s in ai], indent=1))
            if all(clip(s).exists() for s in ai):
                break
            try:
                gpu_step("ltx", "encode", str(d), env=env)
                gpu_step("ltx", "animate", str(d), env=env)
                gpu_step("drift", str(d), env=env)
            except RuntimeError as e:  # AI motion is a bonus; parallax still gives a finished video
                log.warning("AI motion ไม่สำเร็จ (%s) ใช้ภาพ 2.5 มิติแทน", e)
                break

    (d / "jobs_parallax.json").write_text(json.dumps([
        {"image": str(shot(s)), "out": str(clip(s)), "seconds": seconds[s["id"]] + 0.2, "seed": seed(s)}
        for s in part["shots"]], indent=1))  # skips shots that already have a clip
    gpu_step("parallax", str(d), env=env)

    final = render.run(d, cfg)
    if not check:
        return final
    result = qc.run(d, cfg)
    log.info("QC %s: %s", "ผ่าน" if result["passed"] else "ไม่ผ่าน", final)
    return final
