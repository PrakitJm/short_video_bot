import json
import shutil

import pytest

from autovideo import db, orchestrator as orch
from autovideo.config import load_config

CFG = load_config()
CFG["worker"]["retry_base_seconds"] = 0
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db, "JOBS_DIR", tmp_path / "jobs")


def drain(worker):
    while worker.tick():
        pass


def status(jid):
    return db.get_job(jid)["status"]


@needs_ffmpeg
def test_full_flow_stops_at_both_approvals():
    w = orch.Orchestrator(CFG, dry_run=True)
    jid = orch.new_job(CFG, "แมว")
    drain(w)
    assert status(jid) == "AWAITING_SCRIPT_APPROVAL"
    assert db.recent_topics() == ["ทดสอบระบบ"]  # FakeLLM's topic got recorded
    assert orch.approve_script(jid)
    drain(w)
    assert status(jid) == "AWAITING_PUBLISH_APPROVAL"  # never uploads on its own
    assert db.get_job(jid)["youtube_video_id"] is None
    assert orch.approve_publish(jid)
    drain(w)
    assert status(jid) == "PUBLISHED" and db.get_job(jid)["youtube_video_id"] == "dryrun1"
    with db.connect() as c:
        trail = [r[0] for r in c.execute("SELECT to_status FROM events WHERE job_id = ? ORDER BY id", (jid,))]
    assert trail == ["NEW", "SCRIPT_DRAFTED", "AWAITING_SCRIPT_APPROVAL", "SCRIPT_APPROVED", "VOICE_DONE",
                     "VISUALS_DONE", "RENDERED", "QC_PASSED", "AWAITING_PUBLISH_APPROVAL", "PUBLISH_APPROVED", "PUBLISHED"]


@needs_ffmpeg
def test_redo_rebuilds_media_and_excludes_photos():
    w = orch.Orchestrator(CFG, dry_run=True)
    jid = orch.new_job(CFG, "x")
    drain(w)
    orch.approve_script(jid)
    drain(w)
    d = db.job_dir(jid)
    (d / "credits.json").write_text(json.dumps({"1": {"id": "p1", "photographer": "A", "url": "u"}}))
    assert orch.redo_media(jid)
    assert status(jid) == "SCRIPT_APPROVED" and not (d / "final.mp4").exists()
    assert json.loads((d / "excluded_images.json").read_text()) == ["p1"]
    drain(w)
    assert status(jid) == "AWAITING_PUBLISH_APPROVAL"


def test_buttons_work_only_once():
    w = orch.Orchestrator(CFG, dry_run=True)
    jid = orch.new_job(CFG, "x")
    drain(w)
    assert orch.approve_script(jid) is True
    assert orch.approve_script(jid) is False
    assert orch.rewrite(jid) is False
    assert orch.approve_publish(jid) is False  # can't skip straight to posting


def test_rewrite_limit():
    w = orch.Orchestrator(CFG, dry_run=True)
    jid = orch.new_job(CFG, "x")
    for n in range(1, orch.MAX_REWRITES + 1):
        drain(w)
        assert orch.rewrite(jid)
        assert db.get_job(jid)["revise_count"] == n
        assert (db.job_dir(jid) / f"script.rejected{n}.json").exists()
    drain(w)
    with pytest.raises(ValueError, match="ครบ"):
        orch.rewrite(jid)


def test_revise_sends_note_and_returns_to_approval(monkeypatch):
    from autovideo.providers import fakes
    llm = fakes.FakeLLM()
    monkeypatch.setattr(orch, "get_llm", lambda cfg, dry: llm)
    w = orch.Orchestrator(CFG, dry_run=True)
    jid = orch.new_job(CFG, "x")
    drain(w)
    assert orch.request_revision(jid, "ซีน 2 ให้สั้นลง")
    assert status(jid) == "REVISING"
    drain(w)
    assert status(jid) == "AWAITING_SCRIPT_APPROVAL"
    assert "ซีน 2 ให้สั้นลง" in llm.calls[-1] and '"scenes"' in llm.calls[-1]


def test_failure_retries_then_fails_then_retry():
    w = orch.Orchestrator(CFG, dry_run=True)
    calls = []
    w.steps["NEW"] = lambda job, d: calls.append(1) or (_ for _ in ()).throw(RuntimeError("boom"))
    jid = orch.new_job(CFG, "x")
    drain(w)
    assert len(calls) == CFG["limits"]["max_retries"]
    job = db.get_job(jid)
    assert job["status"] == "FAILED" and "boom" in job["error"]
    assert orch.retry(jid) and status(jid) == "NEW" and db.get_job(jid)["attempt_count"] == 0


def test_quota_error_postpones_to_tomorrow():
    class Quota(Exception):
        code = 429
    alerts = []
    w = orch.Orchestrator(CFG, dry_run=True, alert=alerts.append)
    w.steps["NEW"] = lambda job, d: (_ for _ in ()).throw(Quota("429"))
    jid = orch.new_job(CFG, "x")
    drain(w)
    job = db.get_job(jid)
    assert job["status"] == "NEW" and job["next_attempt_at"] == db.tomorrow_morning() and alerts


def test_cancel_and_daily_limit():
    for _ in range(CFG["limits"]["max_jobs_per_day"]):
        jid = orch.new_job(CFG)
    with pytest.raises(ValueError, match="max_jobs_per_day"):
        orch.new_job(CFG)
    assert orch.cancel(jid) and not orch.cancel(jid)


def test_bot_builds_without_network():
    from autovideo.bot.telegram_bot import Bot, keyboard
    bot = Bot(CFG, "123456:TEST", 42)
    assert bot.app.handlers
    assert keyboard(7, ["approve", "cancel"]).inline_keyboard[0][0].callback_data == "approve:7"


def test_youtube_meta_has_credits_and_ai_disclosure():
    from autovideo.providers.fakes import sample_script
    from autovideo.steps import publish
    credits = {"1": {"id": "9", "photographer": "Ann", "url": "https://pixabay.com/photos/x-9/"}, "2": None}
    meta = publish.build_meta(sample_script(), credits, CFG)
    assert meta["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    assert "Ann https://pixabay.com/photos/x-9/" in meta["snippet"]["description"]
    assert meta["snippet"]["categoryId"] == "22"


def test_publish_never_uploads_twice(tmp_path):
    from autovideo.providers.fakes import FakeUploader, sample_script
    from autovideo.steps import publish
    (tmp_path / "script.json").write_text(json.dumps(sample_script(), ensure_ascii=False))
    up = FakeUploader()
    assert publish.run(tmp_path, CFG, up) == publish.run(tmp_path, CFG, up) == "dryrun1"
    assert len(up.uploads) == 1


@pytest.mark.parametrize("path", sorted(__import__("pathlib").Path(__file__).parent.parent.glob("drafts/*.json")))
def test_drafts_are_valid(path):
    from autovideo.models import validate_script
    assert validate_script(json.loads(path.read_text(encoding="utf-8"))) == []


def test_new_from_draft_skips_llm(monkeypatch):
    from autovideo import cli
    from autovideo.providers import fakes
    llm = fakes.FakeLLM()
    monkeypatch.setattr(orch, "get_llm", lambda cfg, dry: llm)
    cli.new_cmd(type("A", (), {"script": "drafts/honey.json", "topic": None})())
    jid = db.list_jobs(1)[0]["id"]
    w = orch.Orchestrator(CFG, dry_run=True)
    drain(w)
    assert status(jid) == "AWAITING_SCRIPT_APPROVAL" and llm.calls == []
    assert json.loads((db.job_dir(jid) / "script.json").read_text())["topic"] == "ทำไมน้ำผึ้งไม่บูด"


def test_owner_can_publish_despite_failed_qc():
    jid = orch.new_job(CFG, "x")
    db.transition(jid, "NEW", "QC_FAILED")
    assert orch.approve_publish(jid) and status(jid) == "PUBLISH_APPROVED"
    assert "ไม่ผ่าน QC" in db.last_event(jid, "PUBLISH_APPROVED")["detail"]


@needs_ffmpeg
def test_redo_sends_the_new_video_again():
    w = orch.Orchestrator(CFG, dry_run=True)
    jid = orch.new_job(CFG, "x")
    drain(w)
    orch.approve_script(jid)
    drain(w)
    assert [j["id"] for j in db.pending_notifications(("AWAITING_PUBLISH_APPROVAL",))] == [jid]
    db.update(jid, notified_status="AWAITING_PUBLISH_APPROVAL")  # the bot sent it
    assert db.pending_notifications(("AWAITING_PUBLISH_APPROVAL",)) == []
    orch.redo_media(jid)
    drain(w)
    assert [j["id"] for j in db.pending_notifications(("AWAITING_PUBLISH_APPROVAL",))] == [jid]
