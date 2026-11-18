"""State machine: read a job's status, do one step, save the result, repeat.

Waiting for approval is just sitting in an AWAITING_* status; only the owner's actions
(Telegram buttons or CLI) move a job out of one, through the functions at the bottom."""
import json
import logging
import shutil
import threading
from datetime import datetime, timedelta

from autovideo import db
from autovideo.config import ROOT
from autovideo.providers import get_images, get_llm, get_tts, get_uploader
from autovideo.steps import publish, qc, render, script, visuals, voice

log = logging.getLogger("autovideo")
MAX_REWRITES = 3
DONE = ("PUBLISHED", "CANCELLED")
MEDIA_OUTPUTS = ["audio", "images", "render", "subs.ass", "credits.json", "final.mp4", "preview.mp4", "qc.json",
                 "music.json", "shots", "picks.json", "ltx_embeds.pt", "jobs_sdxl.json", "jobs_ltx.json",
                 "jobs_parallax.json"]


def then(work, to: str):
    """A step that runs `work(job_dir)` and then moves the job to `to`."""
    def step(job, d):
        work(d)
        return to
    return step


class Orchestrator:
    def __init__(self, cfg: dict, dry_run: bool = False, alert=None):
        self.cfg = cfg
        self.dry_run = dry_run
        self.alert = alert or (lambda text: log.warning(text))
        self.steps = {
            "NEW": self._script,
            "SCRIPT_DRAFTED": then(lambda d: None, "AWAITING_SCRIPT_APPROVAL"),
            "REVISING": self._revise,
            "SCRIPT_APPROVED": then(lambda d: voice.run(d, cfg, get_tts(cfg, dry_run)), "VOICE_DONE"),
            "VOICE_DONE": then(lambda d: visuals.run(d, cfg, get_images(cfg, dry_run)), "VISUALS_DONE"),
            "VISUALS_DONE": then(lambda d: render.run(d, cfg), "RENDERED"),
            "RENDERED": lambda job, d: "QC_PASSED" if qc.run(d, cfg)["passed"] else "QC_FAILED",
            "QC_PASSED": then(lambda d: None, "AWAITING_PUBLISH_APPROVAL"),
            "PUBLISH_APPROVED": self._publish,
        }
        # Story parts share the approval/QC/publish statuses but write and make the video differently.
        self.story_steps = {"NEW": self._story_write, "REVISING": self._story_revise,
                            "SCRIPT_APPROVED": self._story_make, "RENDERED": self._story_qc}

    def _story_script(self, job, d, write: bool, note: str | None = None):
        from autovideo.story import run as story_run, write as story_write
        path = ROOT / job["story"]
        story = json.loads(path.read_text(encoding="utf-8"))
        part = next((p for p in story["parts"] if p["part"] == job["part"]), None)
        if write or part is None:
            part = story_write.write_part(path, job["part"], get_llm(self.cfg, self.dry_run),
                                          self.cfg["limits"]["max_retries"], note)
            story = json.loads(path.read_text(encoding="utf-8"))
        d.mkdir(parents=True, exist_ok=True)
        (d / "script.json").write_text(json.dumps(story_run.part_script(story, part), ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        return "SCRIPT_DRAFTED"

    def _story_write(self, job, d):
        # A rewrite ("เขียนใหม่") moved script.json aside and bumped revise_count: ask the LLM for a new part.
        if (d / "script.json").exists():
            return "SCRIPT_DRAFTED"
        return self._story_script(job, d, write=job["revise_count"] > 0)

    def _story_revise(self, job, d):
        return self._story_script(job, d, write=True, note=job["revise_note"])

    def _story_qc(self, job, d):
        # Story parts run up to story.max_seconds (90), not the 60 s limit of knowledge shorts.
        cfg = {**self.cfg, "video": {**self.cfg["video"], "max_seconds": self.cfg["story"]["max_seconds"]}}
        return "QC_PASSED" if qc.run(d, cfg)["passed"] else "QC_FAILED"

    def _story_make(self, job, d):
        from autovideo.story import run as story_run
        redo = d / "redo.txt"  # bumped by "ทำใหม่" so the redraw uses new seeds
        offset = 1000 * int(redo.read_text()) if redo.exists() else 0
        story_run.run(ROOT / job["story"], job["part"], self.cfg, out_dir=d, seed_offset=offset, check=False)
        return "RENDERED"

    def _script(self, job, d):
        data = script.run(d, self.cfg, get_llm(self.cfg, self.dry_run), topic=job["topic"],
                          recent_topics=db.recent_topics(30))
        db.add_topic(data["topic"], job["id"])
        return "SCRIPT_DRAFTED"

    def _revise(self, job, d):
        script.revise(d, self.cfg, get_llm(self.cfg, self.dry_run), job["revise_note"])
        return "SCRIPT_DRAFTED"

    def _publish(self, job, d):
        video_id = publish.run(d, self.cfg, get_uploader(self.dry_run))
        db.update(job["id"], youtube_video_id=video_id)
        return "PUBLISHED"

    def tick(self) -> bool:
        """Advance one runnable job by one step. False when nothing was runnable."""
        job = db.next_runnable(tuple(self.steps))
        if not job:
            return False
        status, job_id = job["status"], job["id"]
        log.info("job %s: %s", job_id, status)
        steps = {**self.steps, **self.story_steps} if job["kind"] == "story" else self.steps
        try:
            to = steps[status](job, db.job_dir(job_id))
        except Exception as e:
            self._failed(job, e)
            return True
        # expect=status: if the owner cancelled meanwhile, this is a no-op.
        db.transition(job_id, status, to, attempt_count=0, error=None, next_attempt_at=None)
        log.info("job %s: -> %s", job_id, to)
        return True

    def _failed(self, job, e: Exception):
        job_id, n = job["id"], job["attempt_count"] + 1
        err = f"{type(e).__name__}: {e}"[:1000]
        log.exception("job %s failed at %s (attempt %s)", job_id, job["status"], n)
        if getattr(e, "code", None) == 429:  # LLM free-tier quota spent for the day
            when = db.tomorrow_morning()
            db.update(job_id, error=err, next_attempt_at=when)
            self.alert(f"⏸ งาน #{job_id}: โควตา AI หมด เลื่อนไปทำต่อ {when}")
        elif n < self.cfg["limits"]["max_retries"]:
            wait = self.cfg["worker"]["retry_base_seconds"] * 2 ** (n - 1)
            when = (datetime.now() + timedelta(seconds=wait)).isoformat(timespec="seconds")
            db.update(job_id, attempt_count=n, error=err, next_attempt_at=when)
        else:
            db.transition(job_id, job["status"], "FAILED", err, attempt_count=n, error=err)

    def run_forever(self, stop: threading.Event):
        while not stop.is_set():
            try:
                worked = self.tick()
            except Exception:  # e.g. database locked; never let the worker thread die
                log.exception("worker tick crashed")
                worked = False
            if not worked:
                stop.wait(self.cfg["worker"]["poll_seconds"])


# --- Owner actions. Each returns False when the job isn't in a state that allows it. ---

def new_job(cfg: dict, topic: str | None = None) -> int:
    limit = cfg["limits"]["max_jobs_per_day"]
    if db.jobs_created_today() >= limit:
        raise ValueError(f"วันนี้สร้างงานครบ {limit} งานแล้ว (limits.max_jobs_per_day)")
    return db.create_job(topic)


def all_parts(story_path) -> list[int]:
    story = json.loads((ROOT / story_path).read_text(encoding="utf-8"))
    return sorted({p["part"] for p in story["parts"] + story.get("outline", [])})


def new_story_job(cfg: dict, story_path: str, part: int | None = None) -> int:
    """Queue one part of a story (default: the next part that has no job yet)."""
    queued = db.story_parts_queued(story_path)
    parts = all_parts(story_path)
    if part is None:
        part = next((p for p in parts if p not in queued), None)
        if part is None:
            raise ValueError(f"{story_path}: ทุกตอนมีงานแล้ว ({len(parts)} ตอน)")
    elif part in queued:
        raise ValueError(f"ตอนที่ {part} มีงานอยู่แล้ว (ยกเลิกงานเดิมก่อนถ้าจะทำใหม่)")
    limit = cfg["limits"]["max_jobs_per_day"]
    if db.jobs_created_today() >= limit:
        raise ValueError(f"วันนี้สร้างงานครบ {limit} งานแล้ว (limits.max_jobs_per_day)")
    series = json.loads((ROOT / story_path).read_text(encoding="utf-8"))["series"]
    return db.create_job(f"{series} ตอนที่ {part}", kind="story", story=story_path, part=part)


def approve_script(job_id: int) -> bool:
    return db.transition(job_id, "AWAITING_SCRIPT_APPROVAL", "SCRIPT_APPROVED", "อนุมัติบท")


def rewrite(job_id: int) -> bool:
    job = db.get_job(job_id)
    if not job or job["status"] != "AWAITING_SCRIPT_APPROVAL":
        return False
    if job["revise_count"] >= MAX_REWRITES:
        raise ValueError(f"เขียนใหม่ครบ {MAX_REWRITES} รอบแล้ว ให้กดอนุมัติ แก้ไข หรือยกเลิก")
    d = db.job_dir(job_id)
    if (d / "script.json").exists():  # keep the rejected draft for reference
        (d / "script.json").replace(d / f"script.rejected{job['revise_count'] + 1}.json")
    return db.transition(job_id, "AWAITING_SCRIPT_APPROVAL", "NEW", "เขียนใหม่", revise_count=job["revise_count"] + 1)


def request_revision(job_id: int, note: str) -> bool:
    return db.transition(job_id, "AWAITING_SCRIPT_APPROVAL", "REVISING", f"แก้ไข: {note}", revise_note=note)


def approve_publish(job_id: int) -> bool:
    """Also allowed from QC_FAILED: the owner watched the video and decided the failed check doesn't matter
    (e.g. a story part a few seconds over the length limit)."""
    job = db.get_job(job_id)
    detail = "อนุมัติโพสต์ (เจ้าของยืนยันแม้ไม่ผ่าน QC)" if job and job["status"] == "QC_FAILED" else "อนุมัติโพสต์"
    return db.transition(job_id, ("AWAITING_PUBLISH_APPROVAL", "QC_FAILED"), "PUBLISH_APPROVED", detail)


def redo_media(job_id: int) -> bool:
    """"ทำใหม่": keep the approved script, redo voice and visuals with different photos."""
    job = db.get_job(job_id)
    if not job or job["status"] not in ("AWAITING_PUBLISH_APPROVAL", "QC_FAILED"):
        return False
    d = db.job_dir(job_id)
    if job["kind"] == "story":
        redo = d / "redo.txt"
        redo.write_text(str(int(redo.read_text()) + 1 if redo.exists() else 1))
    credits = d / "credits.json"
    if credits.exists():
        excluded_path = d / "excluded_images.json"
        excluded = json.loads(excluded_path.read_text()) if excluded_path.exists() else []
        excluded += [c["id"] for c in json.loads(credits.read_text()).values() if c]
        excluded_path.write_text(json.dumps(sorted(set(excluded))))
    for name in MEDIA_OUTPUTS:
        p = d / name
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    return db.transition(job_id, ("AWAITING_PUBLISH_APPROVAL", "QC_FAILED"), "SCRIPT_APPROVED", "ทำใหม่")


def cancel(job_id: int) -> bool:
    job = db.get_job(job_id)
    if not job or job["status"] in DONE:
        return False
    return db.transition(job_id, job["status"], "CANCELLED", "ยกเลิก")


def retry(job_id: int) -> bool:
    job = db.get_job(job_id)
    if not job:
        return False
    if job["status"] == "QC_FAILED":
        return redo_media(job_id)
    if job["status"] != "FAILED":
        return False
    before = db.last_event(job_id, "FAILED")["from_status"]
    return db.transition(job_id, "FAILED", before, "ลองใหม่", attempt_count=0, error=None, next_attempt_at=None)
