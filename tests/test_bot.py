import asyncio
from types import SimpleNamespace as NS

import pytest

from autovideo import db, orchestrator as orch
from autovideo.bot.telegram_bot import Bot
from autovideo.config import load_config

CFG = load_config()
OWNER = 42


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db, "JOBS_DIR", tmp_path / "jobs")


class Query:
    def __init__(self, data, chat=OWNER):
        self.data, self.message = data, NS(chat=NS(id=chat), text="บท")
        self.answers, self.edits, self.markup_cleared = [], [], False

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text):
        self.edits.append(text)

    async def edit_message_reply_markup(self, markup):
        self.markup_cleared = True


def press(bot, data, chat=OWNER, ctx=None):
    q = Query(data, chat)
    asyncio.run(bot.on_button(NS(callback_query=q), ctx or NS(chat_data={})))
    return q


@pytest.fixture
def awaiting_script():
    w = orch.Orchestrator(CFG, dry_run=True)
    jid = orch.new_job(CFG, "x")
    while w.tick():
        pass
    return jid


def test_approve_button_once(awaiting_script):
    bot = Bot(CFG, "1:T", OWNER)
    q = press(bot, f"approve:{awaiting_script}")
    assert db.get_job(awaiting_script)["status"] == "SCRIPT_APPROVED" and "อนุมัติ" in q.edits[0]
    q2 = press(bot, f"approve:{awaiting_script}")
    assert q2.answers == ["ปุ่มนี้ใช้ไปแล้ว"] and q2.markup_cleared


def test_strangers_are_ignored(awaiting_script):
    bot = Bot(CFG, "1:T", OWNER)
    q = press(bot, f"approve:{awaiting_script}", chat=999)
    assert q.answers == [] and db.get_job(awaiting_script)["status"] == "AWAITING_SCRIPT_APPROVAL"


def test_revise_button_then_text(awaiting_script):
    bot = Bot(CFG, "1:T", OWNER)
    ctx = NS(chat_data={})
    press(bot, f"revise:{awaiting_script}", ctx=ctx)
    assert ctx.chat_data["revise_job"] == awaiting_script
    replies = []
    msg = NS(text="ทำให้ตลกขึ้น", reply_text=lambda t: asyncio.sleep(0, replies.append(t)))
    asyncio.run(bot.on_text(NS(message=msg), ctx))
    job = db.get_job(awaiting_script)
    assert job["status"] == "REVISING" and job["revise_note"] == "ทำให้ตลกขึ้น"


def test_script_notification_has_buttons(awaiting_script):
    bot = Bot(CFG, "1:T", OWNER)
    sent = []

    async def say(text, **kw):
        sent.append((text, kw))
    bot.say = say
    asyncio.run(bot.notify(db.get_job(awaiting_script)))
    text, kw = sent[0]
    labels = [b.text for b in kw["reply_markup"].inline_keyboard[0]]
    assert labels == ["อนุมัติ", "เขียนใหม่", "แก้ไข", "ยกเลิก"] and "นี่คือบทพากย์" in text


def test_help_lists_every_command():
    from autovideo.bot.telegram_bot import COMMANDS, HELP
    assert all(f"/{name}" in HELP for name, _ in COMMANDS)


def test_list_groups_jobs_by_what_they_need(awaiting_script):
    from autovideo.bot.telegram_bot import job_list
    from autovideo import orchestrator as orch
    other = orch.new_job(CFG, "อีกงาน")
    orch.cancel(other)
    text = job_list()
    assert "⏳ รอคุณ" in text and "ยืนยันบท" in text and "🚫 ยกเลิก" in text and f"#{other}" in text


def test_startup_message_says_when_and_how_it_went_down(awaiting_script):
    from autovideo.bot import telegram_bot as tb
    tb.write_heartbeat("running")
    assert "ดับกะทันหัน" in tb.startup_message()
    tb.write_heartbeat("clean")
    assert "ปิดตามปกติ" in tb.startup_message()
    orch.approve_script(awaiting_script)
    assert f"#{awaiting_script}" in tb.startup_message()  # approved = the worker will carry on with it


def test_report_toggle_is_saved():
    from autovideo.bot import telegram_bot as tb
    assert tb.setting("progress_reports") is True  # default on
    tb.set_setting("progress_reports", False)
    assert tb.setting("progress_reports") is False


def test_eta_counts_remaining_story_work(tmp_path):
    from autovideo import eta
    jid = db.create_job("นิทาน ตอนที่ 1", kind="story", story="drafts/stories/system_loop.json", part=1)
    d = db.job_dir(jid)
    (d / "shots").mkdir(parents=True)
    r = {"draw": 100, "ltx": 300, "parallax": 10}
    left_all, stage = eta.story_remaining(db.get_job(jid), CFG, r)
    assert stage == "ลงเสียง" and left_all > 54 * 100  # 18 shots x 3 takes still to draw
    for i in range(1, 19):
        for k in range(3):
            (d / "shots" / f"shot_{i:02d}.c{k}.png").write_bytes(b"x")
    left_drawn, stage = eta.story_remaining(db.get_job(jid), CFG, r)
    assert left_drawn < left_all - 50 * 100 and stage == "ลงเสียง"
    assert "เหลือ" in eta.eta_text(CFG) or "รอคุณ" in eta.eta_text(CFG)
