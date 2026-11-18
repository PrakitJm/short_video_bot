"""SQLite storage. Every status change goes through `transition`, which also writes an event row."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from autovideo.config import ROOT

DB_PATH = ROOT / "data/app.db"
JOBS_DIR = ROOT / "data/jobs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    topic TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    revise_count INTEGER NOT NULL DEFAULT 0,
    revise_note TEXT,
    error TEXT,
    youtube_video_id TEXT,
    next_attempt_at TEXT,
    notified_status TEXT,
    kind TEXT NOT NULL DEFAULT 'short',
    story TEXT,
    part INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    job_id INTEGER REFERENCES jobs(id),
    created_at TEXT NOT NULL
);
"""
# Columns added after the first release; ALTERed into older databases on connect.
MIGRATIONS = {"kind": "TEXT NOT NULL DEFAULT 'short'", "story": "TEXT", "part": "INTEGER"}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    path = DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # One short-lived connection per call: the bot and the worker thread each get their own.
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for col, decl in MIGRATIONS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def job_dir(job_id: int) -> Path:
    return JOBS_DIR / str(job_id)


def create_job(topic: str | None = None, kind: str = "short", story: str | None = None, part: int | None = None) -> int:
    with connect() as c:
        t = now()
        cur = c.execute("INSERT INTO jobs (status, topic, kind, story, part, created_at, updated_at) "
                        "VALUES ('NEW', ?, ?, ?, ?, ?, ?)", (topic, kind, story, part, t, t))
        c.execute("INSERT INTO events (job_id, from_status, to_status, detail, created_at) VALUES (?, NULL, 'NEW', ?, ?)",
                  (cur.lastrowid, topic, t))
        return cur.lastrowid


def get_job(job_id: int) -> sqlite3.Row | None:
    with connect() as c:
        return c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs(limit: int = 10) -> list[sqlite3.Row]:
    with connect() as c:
        return c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def transition(job_id: int, expect: str | tuple[str, ...], to: str, detail: str | None = None, **fields) -> bool:
    """Move a job to `to` only if it is currently in `expect`. False means someone else got there first
    (e.g. a Telegram button pressed twice), so callers never act on a stale status."""
    expect = (expect,) if isinstance(expect, str) else expect
    # Every status change re-arms the owner notification, so a job that comes back to a status it was in
    # before (e.g. "ทำใหม่" -> waiting for publish approval again) sends the new video too.
    fields = {"notified_status": None, **fields}
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect() as c:
        row = c.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row or row["status"] not in expect:
            return False
        t = now()
        c.execute(f"UPDATE jobs SET status = ?, updated_at = ?{', ' + sets if sets else ''} WHERE id = ?",
                  (to, t, *fields.values(), job_id))
        c.execute("INSERT INTO events (job_id, from_status, to_status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                  (job_id, row["status"], to, detail, t))
        return True


def update(job_id: int, **fields) -> None:
    with connect() as c:
        sets = ", ".join(f"{k} = ?" for k in fields)
        c.execute(f"UPDATE jobs SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), now(), job_id))


def last_event(job_id: int, to_status: str) -> sqlite3.Row | None:
    with connect() as c:
        return c.execute("SELECT * FROM events WHERE job_id = ? AND to_status = ? ORDER BY id DESC LIMIT 1",
                         (job_id, to_status)).fetchone()


def next_runnable(statuses: tuple[str, ...]) -> sqlite3.Row | None:
    marks = ",".join("?" * len(statuses))
    with connect() as c:
        return c.execute(
            f"SELECT * FROM jobs WHERE status IN ({marks}) AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY id LIMIT 1", (*statuses, now())).fetchone()


def story_parts_queued(story: str) -> set[int]:
    """Parts of a story that already have a job (cancelled ones don't count, so they can be redone)."""
    with connect() as c:
        return {r[0] for r in c.execute(
            "SELECT part FROM jobs WHERE kind = 'story' AND story = ? AND status != 'CANCELLED'", (story,))}


def jobs_created_today() -> int:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM jobs WHERE created_at >= ?", (start,)).fetchone()[0]


def add_topic(topic: str, job_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM topics WHERE job_id = ?", (job_id,))  # a rewrite replaces the job's topic
        c.execute("INSERT INTO topics (topic, job_id, created_at) VALUES (?, ?, ?)", (topic, job_id, now()))


def recent_topics(limit: int = 30) -> list[str]:
    with connect() as c:
        return [r[0] for r in c.execute("SELECT topic FROM topics ORDER BY id DESC LIMIT ?", (limit,))]


def pending_notifications(statuses: tuple[str, ...]) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(statuses))
    with connect() as c:
        return c.execute(f"SELECT * FROM jobs WHERE status IN ({marks}) AND notified_status IS NOT status ORDER BY id",
                         statuses).fetchall()


def tomorrow_morning() -> str:
    t = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    return t.isoformat(timespec="seconds")
