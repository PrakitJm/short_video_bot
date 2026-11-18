"""Estimate when queued jobs finish, from how fast this machine actually worked recently.

Speeds come from file timestamps of past and current story jobs (one drawn take, one AI clip, one 2.5D clip
each), so a hot, throttled GPU automatically makes the estimate longer."""
import json
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

from autovideo import db
from autovideo.config import ROOT

DEFAULTS = {"draw": 140, "ltx": 300, "parallax": 15}  # seconds per take / AI clip / 2.5D clip
OVERHEAD = {"voice": 60, "draw": 150, "pick": 60, "ltx": 240, "parallax": 30, "render": 120}
SHORT_MAKE = 300     # a knowledge short from approval to the finished video
STORY_WRITE = 30     # writing/reading a story part's script
DONE = ("PUBLISHED", "CANCELLED", "FAILED")
WAITING = ("AWAITING_SCRIPT_APPROVAL", "AWAITING_PUBLISH_APPROVAL", "QC_FAILED")


def _gaps(paths: list[Path], lo: float = 5, hi: float = 1800) -> list[tuple[float, float]]:
    """(finish time, seconds since the previous one) for files made one after another."""
    t = sorted(p.stat().st_mtime for p in paths)
    return [(b, b - a) for a, b in zip(t, t[1:]) if lo < b - a < hi]


def story_dirs() -> list[Path]:
    dirs = [d for d in db.JOBS_DIR.glob("*") if (d / "jobs_sdxl.json").exists()]
    return dirs + list((db.JOBS_DIR.parent / "stories").glob("*/part*"))


def ai_names(d: Path) -> set[str]:
    p = d / "jobs_ltx.json"
    return {Path(j["out"]).name for j in json.loads(p.read_text())} if p.exists() else set()


def rates(recent: int = 30) -> dict:
    """Median seconds per unit over the most recent `recent` measurements (defaults when none yet)."""
    samples = {"draw": [], "ltx": [], "parallax": []}
    for d in story_dirs():
        ai = ai_names(d)
        clips = list((d / "images").glob("scene_??.mp4"))
        samples["draw"] += _gaps(list((d / "shots").glob("*.c[0-9].png")))
        samples["ltx"] += _gaps([c for c in clips if c.name in ai])
        samples["parallax"] += _gaps([c for c in clips if c.name not in ai], lo=1)
    out = {}
    for k, s in samples.items():
        s = [g for _, g in sorted(s)[-recent:]]
        out[k] = statistics.median(s) if s else DEFAULTS[k]
    return out


def _story_shots(job, d: Path) -> tuple[int, set[str]]:
    """Number of shots and the clip names that get AI motion, before or after the video step starts."""
    ai = ai_names(d)
    try:
        story = json.loads((ROOT / job["story"]).read_text(encoding="utf-8"))
        part = next(p for p in story["parts"] if p["part"] == job["part"])
        shots = len(part["shots"])
        ai = ai or {f"scene_{s['id']:02d}.mp4" for s in part["shots"] if s.get("motion") == "ai"}
    except (OSError, StopIteration, KeyError, TypeError, json.JSONDecodeError):
        shots = 18
    return shots, ai


def story_remaining(job, cfg: dict, r: dict, now: float | None = None) -> tuple[float, str]:
    """Seconds left to make a story part's video, and which stage it is in."""
    now = now or time.time()
    d = db.job_dir(job["id"])
    shots, ai = _story_shots(job, d)
    if cfg["story"].get("ai_all"):
        ai = {f"scene_{i:02d}.mp4" for i in range(1, shots + 1)}
    if not cfg["story"].get("ai_motion", True):
        ai = set()
    want = shots * cfg["story"].get("candidates", 1)
    takes = list((d / "shots").glob("*.c[0-9].png"))
    clips = {p.name: p for p in (d / "images").glob("scene_??.mp4")}
    voiced = len(list((d / "audio").glob("*.words.json")))
    picked = len(list((d / "shots").glob("shot_??.png")))
    ai_done = sum(n in clips for n in ai)
    par_done = len(clips) - ai_done

    def since(paths):  # time spent on the unit in progress (counts toward it)
        return now - max((p.stat().st_mtime for p in paths), default=now)

    left, stage = 0.0, None
    if voiced < shots:
        left += OVERHEAD["voice"]
        stage = stage or "ลงเสียง"
    if len(takes) < want:
        warm = since(takes) < 2 * r["draw"]
        left += (0 if warm else OVERHEAD["draw"]) + (want - len(takes)) * r["draw"] - min(since(takes), r["draw"] * 0.9)
        stage = stage or f"วาดภาพ {len(takes)}/{want}"
    if picked < shots:
        left += OVERHEAD["pick"]
        stage = stage or "เลือกภาพ"
    if ai_done < len(ai):
        ai_clips = [clips[n] for n in ai if n in clips]
        warm = since(ai_clips) < 2 * r["ltx"]
        left += (0 if warm else OVERHEAD["ltx"]) + (len(ai) - ai_done) * r["ltx"] - min(since(ai_clips), r["ltx"] * 0.9)
        stage = stage or f"AI ทำให้ขยับ {ai_done}/{len(ai)}"
    if par_done < shots - len(ai):
        left += OVERHEAD["parallax"] + (shots - len(ai) - par_done) * r["parallax"]
        stage = stage or f"ภาพ 2.5 มิติ {par_done}/{shots - len(ai)}"
    if not (d / "final.mp4").exists():
        left += OVERHEAD["render"]
        stage = stage or "ตัดต่อ"
    return max(left, 30), stage or "ตรวจ QC"


def full_story(cfg: dict, r: dict) -> float:
    """A whole story part from approval, at today's speeds."""
    shots = 18
    ai = (shots if cfg["story"].get("ai_all") else 6) if cfg["story"].get("ai_motion", True) else 0
    return (sum(OVERHEAD.values()) + shots * cfg["story"].get("candidates", 1) * r["draw"]
            + ai * r["ltx"] + (shots - ai) * r["parallax"])


def fmt(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m // 60} ชม. {m % 60} นาที" if m >= 60 else f"{max(m, 1)} นาที"


def eta_text(cfg: dict) -> str:
    """Telegram /eta: the worker does one job at a time in id order, so finish times add up."""
    r = rates()
    clock = datetime.now()
    lines, waiting = [], []
    for job in sorted(db.list_jobs(50), key=lambda j: j["id"]):
        st, name, story = job["status"], job["topic"] or "(AI เลือก)", job["kind"] == "story"
        if st in DONE:
            continue
        if st in WAITING:
            after = (fmt(full_story(cfg, r)) if story else fmt(SHORT_MAKE)) if st == "AWAITING_SCRIPT_APPROVAL" else "~1 นาที (อัปโหลด)"
            what = {"AWAITING_SCRIPT_APPROVAL": "ยืนยันบท", "AWAITING_PUBLISH_APPROVAL": "ยืนยันโพสต์",
                    "QC_FAILED": "ตัดสินใจ (ไม่ผ่าน QC)"}[st]
            waiting.append(f"#{job['id']} {name} — รอคุณ{what} · หลังกดใช้ {after}")
            continue
        if st == "SCRIPT_APPROVED" and story:
            left, stage = story_remaining(job, cfg, r)
        elif st in ("NEW", "REVISING", "SCRIPT_DRAFTED"):
            left, stage = STORY_WRITE if story else 60, "เขียนบท"
        elif st == "PUBLISH_APPROVED":
            left, stage = 60, "อัปโหลด"
        else:
            left, stage = SHORT_MAKE / 2, "ทำวิดีโอ"
        clock += timedelta(seconds=left)
        lines.append(f"#{job['id']} {name}\n   {stage} · เหลือ ~{fmt(left)} · เสร็จ ~{clock:%H:%M}")
    out = ["⏳ คาดการณ์เวลา"] + (lines or ["ไม่มีงานที่กำลังทำ"])
    if waiting:
        out += ["", "รอคุณกด:"] + waiting
    out += ["", f"ความเร็วเครื่องตอนนี้: วาดภาพ {r['draw']:.0f} วิ/ภาพ · AI ขยับ {r['ltx'] / 60:.1f} นาที/ช็อต"
                f" · นิทาน 1 ตอน ~{fmt(full_story(cfg, r))}"]
    return "\n".join(out)
