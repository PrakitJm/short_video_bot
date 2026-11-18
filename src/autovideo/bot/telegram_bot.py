"""Owner-only Telegram bot. It never does pipeline work itself: buttons and commands only change
job status (via orchestrator actions), and a loop sends a message whenever a job needs the owner."""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from autovideo import db, eta, orchestrator as orch
from autovideo.orchestrator import MAX_REWRITES
from autovideo.steps import publish

log = logging.getLogger("autovideo")
PROGRESS_EVERY = 600  # seconds between story progress reports
NOTIFY = ("AWAITING_SCRIPT_APPROVAL", "AWAITING_PUBLISH_APPROVAL", "QC_FAILED", "FAILED", "PUBLISHED")
STATUS_TH = {
    "NEW": "กำลังเขียนบท", "SCRIPT_DRAFTED": "ได้บทแล้ว", "AWAITING_SCRIPT_APPROVAL": "รอยืนยันบท",
    "REVISING": "กำลังแก้บท", "SCRIPT_APPROVED": "กำลังทำเสียง", "VOICE_DONE": "กำลังหาภาพ",
    "VISUALS_DONE": "กำลังตัดต่อ", "RENDERED": "กำลังตรวจ QC", "QC_PASSED": "ผ่าน QC",
    "QC_FAILED": "ไม่ผ่าน QC", "AWAITING_PUBLISH_APPROVAL": "รอยืนยันโพสต์", "PUBLISH_APPROVED": "กำลังอัปโหลด",
    "PUBLISHED": "โพสต์แล้ว", "CANCELLED": "ยกเลิก", "FAILED": "ล้มเหลว",
}
LABELS = {"approve": "อนุมัติ", "rewrite": "เขียนใหม่", "revise": "แก้ไข", "cancel": "ยกเลิก",
          "publish": "โพสต์", "redo": "ทำใหม่"}
HELP = """🤖 คำสั่งทั้งหมด

/new [หัวข้อ] — สร้างคลิปใหม่ 1 งาน
  เช่น /new ทำไมแมวชอบกล่อง
  ไม่ใส่หัวข้อ = ให้ AI เลือกเอง (ต้องมีคีย์ Gemini)
  วันละไม่เกิน limits.max_jobs_per_day งาน

/status — ดู 10 งานล่าสุด และแต่ละงานอยู่ขั้นไหน (แบบสั้น)

/story [ตอน] — ใส่นิทานตอนถัดไปลงคิว เช่น /story หรือ /story 5
  เรื่องที่ใช้ตั้งใน story.series ของ config.yaml
  ตอนที่ยังไม่มีบท AI จะเขียนจากโครงเรื่องแล้วส่งมาให้อนุมัติก่อน
  หลังอนุมัติใช้เวลาทำ ~1.5-2 ชม. (วาดภาพบนการ์ดจอ) แล้วส่งคลิปมาให้กดโพสต์

/list — ลิสต์งานทั้งหมดแยกเป็นกลุ่ม: รอคุณ / กำลังทำ / ล้มเหลว / เสร็จแล้ว
  รวมงานนิทานทุกตอนด้วย

/progress — ดูความคืบหน้านิทานที่กำลังทำ

/eta — คาดการณ์ว่าแต่ละงานจะเสร็จกี่โมง (คิดจากความเร็วจริงล่าสุดของเครื่อง)

/report on | off — เปิด/ปิดรายงานความคืบหน้าทุก 10 นาที ระหว่างทำนิทาน
  พิมพ์ /report เฉยๆ = ดูว่าเปิดอยู่หรือไม่
  ปิดแล้วยังแจ้งเสมอ: บทพร้อมให้อนุมัติ, คลิปเสร็จ (ส่งคลิป), ไม่ผ่าน QC, ล้มเหลว, โพสต์แล้ว, ระบบเปิด/ปิด

/cancel <เลขงาน> — ยกเลิกงาน เช่น /cancel 3

/retry <เลขงาน> — ลองใหม่งานที่ล้มเหลว เช่น /retry 3
  ถ้างานไม่ผ่าน QC จะทำเสียงและภาพใหม่

/help — แสดงหน้านี้

🔘 ปุ่มที่จะเจอ
ตอนรอยืนยันบท:
  อนุมัติ = ไปทำเสียง ภาพ ตัดต่อต่อ
  เขียนใหม่ = ทิ้งบทนี้ ให้ AI เขียนใหม่ (ได้ 3 ครั้ง)
  แก้ไข = กดแล้วพิมพ์สิ่งที่อยากแก้ส่งมา AI จะแก้ตามนั้น
  ยกเลิก = เลิกทำงานนี้
ตอนรอยืนยันโพสต์ หรือไม่ผ่าน QC (ส่งคลิปมาให้ดูก่อนทั้งสองแบบ):
  โพสต์ = อัปโหลดขึ้น YouTube ตาม youtube.privacy
    (ไม่ผ่าน QC แต่ดูแล้วใช้ได้ เช่นยาวเกินนิดหน่อย ก็กดโพสต์ได้)
  ทำใหม่ = ใช้บทเดิม แต่ทำเสียงและหาภาพใหม่ (ไม่ใช้ภาพเดิมซ้ำ)
  ยกเลิก = เลิกทำงานนี้

ปุ่มแต่ละอันกดได้ครั้งเดียว ไม่มีอะไรถูกโพสต์ถ้าไม่กด "โพสต์" เอง"""
COMMANDS = [("new", "สร้างคลิปใหม่ /new [หัวข้อ]"), ("story", "นิทานตอนถัดไป /story [ตอน]"), ("list", "ลิสต์งานทั้งหมดแยกกลุ่ม"), ("status", "ดูงานล่าสุด"), ("progress", "ความคืบหน้านิทาน"), ("eta", "คาดการณ์เวลาเสร็จ"),
            ("report", "เปิด/ปิดรายงานทุก 10 นาที /report on|off"),
            ("cancel", "ยกเลิกงาน /cancel <เลข>"), ("retry", "ลองใหม่ /retry <เลข>"), ("help", "วิธีใช้ทุกคำสั่ง")]
ACTIONS = {"approve": orch.approve_script, "rewrite": orch.rewrite, "publish": orch.approve_publish,
           "redo": orch.redo_media, "cancel": orch.cancel}


def keyboard(job_id: int, actions: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(LABELS[a], callback_data=f"{a}:{job_id}") for a in actions]])


def read_json(job_id: int, name: str) -> dict:
    p = db.job_dir(job_id) / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def script_text(job_id: int) -> str:
    s = read_json(job_id, "script.json")
    scenes = "\n".join(f"{x['id']}. {x['narration']}" + ("" if x["visual_query"] == "story" else f"\n   🖼 {x['visual_query']}")
                       for x in s.get("scenes", []))
    return f"📝 งาน #{job_id} รอยืนยันบท\n\n<{s.get('title')}>\nหัวข้อ: {s.get('topic')}\n\n{scenes}"[:4000]


def qc_text(job_id: int) -> str:
    q = read_json(job_id, "qc.json")
    return "\n".join(f"{'✓' if c['ok'] else '✗'} {k}: {c['detail']}" for k, c in q.get("checks", {}).items())


WAITING = {"AWAITING_SCRIPT_APPROVAL": "ยืนยันบท", "AWAITING_PUBLISH_APPROVAL": "ยืนยันโพสต์", "QC_FAILED": "ไม่ผ่าน QC"}


def job_list(limit: int = 50) -> str:
    """Every job grouped by what it needs, plus story parts, for /list."""
    groups = {"⏳ รอคุณ": [], "⚙️ กำลังทำ": [], "❌ ล้มเหลว": [], "✅ โพสต์แล้ว": [], "🚫 ยกเลิก": []}
    for j in db.list_jobs(limit):
        st, name = j["status"], j["topic"] or "(AI เลือก)"
        if st in WAITING:
            groups["⏳ รอคุณ"].append(f"#{j['id']} {name} → {WAITING[st]} (กดปุ่มในข้อความของงานนี้)")
        elif st == "FAILED":
            groups["❌ ล้มเหลว"].append(f"#{j['id']} {name} → /retry {j['id']}")
        elif st == "PUBLISHED":
            groups["✅ โพสต์แล้ว"].append(f"#{j['id']} {name} https://youtube.com/shorts/{j['youtube_video_id']}")
        elif st == "CANCELLED":
            groups["🚫 ยกเลิก"].append(f"#{j['id']} {name}")
        else:
            groups["⚙️ กำลังทำ"].append(f"#{j['id']} {name} — {STATUS_TH.get(st, st)}")
    groups["🚫 ยกเลิก"] = groups["🚫 ยกเลิก"][:5]  # old cancelled jobs are noise
    out = [f"{title}\n" + "\n".join(rows) for title, rows in groups.items() if rows]
    return ("\n\n".join(out) or "ยังไม่มีงาน สร้างด้วย /new [หัวข้อ]")[:4000]


SETTINGS = {"progress_reports": True}  # defaults; changes are saved to data/settings.json


def setting(key: str):
    try:
        return {**SETTINGS, **json.loads((db.JOBS_DIR.parent / "settings.json").read_text())}[key]
    except (OSError, ValueError):
        return SETTINGS[key]


def set_setting(key: str, value) -> None:
    p = db.JOBS_DIR.parent / "settings.json"
    try:
        current = json.loads(p.read_text())
    except (OSError, ValueError):
        current = {}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**current, key: value}))


def story_progress(job=None, cfg: dict | None = None) -> str:
    """How far the newest story job (or `job`) has got: takes drawn, shots picked, clips made."""
    if job is None:
        job = next((j for j in db.list_jobs(50) if j["kind"] == "story"), None)
    if job is None:
        return "ยังไม่มีงานนิทาน สร้างด้วย /story"
    d = db.job_dir(job["id"])
    spec = json.loads((d / "jobs_sdxl.json").read_text()) if (d / "jobs_sdxl.json").exists() else {"jobs": []}
    want = sum(j.get("candidates", 1) for j in spec["jobs"])
    shots = len(spec["jobs"])
    drawn = len(list((d / "shots").glob("*.c[0-9].png")))
    picked = len(list((d / "shots").glob("shot_??.png")))
    clips = len(list((d / "images").glob("scene_??.mp4")))
    step = ("✅ ตัดต่อเสร็จ" if (d / "final.mp4").exists() else "ทำให้ขยับ/ตัดต่อ" if picked
            else "วาดภาพ" if spec["jobs"] else "ลงเสียง/เตรียม")
    status = "กำลังทำวิดีโอ" if job["status"] == "SCRIPT_APPROVED" else STATUS_TH.get(job["status"], job["status"])
    out = (f"📊 งาน #{job['id']} {job['topic']}\nสถานะ: {status} — {step}\n"
           f"วาดแล้ว {drawn}/{want or '?'} | เลือกภาพ {picked}/{shots or '?'} | คลิป {clips}/{shots or '?'}")
    if cfg and job["status"] == "SCRIPT_APPROVED":
        left, _ = eta.story_remaining(job, cfg, eta.rates())
        out += f"\nเหลือ ~{eta.fmt(left)} · เสร็จ ~{datetime.fromtimestamp(time.time() + left):%H:%M}"
    return out


HEARTBEAT = "heartbeat.txt"  # "<iso time> running|clean" in data/, refreshed every poll


def heartbeat_path():
    return db.JOBS_DIR.parent / HEARTBEAT


def write_heartbeat(state: str) -> None:
    heartbeat_path().parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path().write_text(f"{datetime.now().isoformat(timespec='seconds')} {state}")


def busy_text() -> str:
    """Jobs the worker will carry on with, e.g. 'งานที่ทำค้าง: #4 ...'."""
    waiting = set(WAITING) | {"PUBLISHED", "CANCELLED", "FAILED"}
    busy = [f"#{j['id']} {j['topic'] or '(AI เลือก)'}" for j in db.list_jobs(50) if j["status"] not in waiting]
    return ("งานที่ทำค้าง: " + ", ".join(busy)) if busy else ""


def startup_message() -> str:
    msg = f"🟢 ระบบเปิดแล้ว {datetime.now():%H:%M}"
    try:
        when, state = heartbeat_path().read_text().split()
        down = datetime.fromisoformat(when)
        msg += f"\nปิดไปตั้งแต่ {down:%d/%m %H:%M}" + (" (ปิดตามปกติ)" if state == "clean" else " (ดับกะทันหัน เช่น WSL ถูกปิด/คอมดับ)")
    except (OSError, ValueError):
        pass
    busy = busy_text()
    return msg + (f"\n{busy} — ทำต่อจากที่ค้างให้เลย" if busy else "")


class Bot:
    def __init__(self, cfg: dict, token: str, owner_chat_id: int, worker: orch.Orchestrator | None = None):
        self.cfg, self.owner, self.worker = cfg, owner_chat_id, worker
        self.app = (Application.builder().token(token).post_init(self._start).post_stop(self._stopping)
                    .post_shutdown(self._stop).build())
        only_owner = filters.Chat(chat_id=owner_chat_id)  # everyone else is ignored
        for name, fn in [("new", self.cmd_new), ("status", self.cmd_status), ("list", self.cmd_list),
                         ("cancel", self.cmd_cancel),
                         ("retry", self.cmd_retry), ("start", self.cmd_help), ("help", self.cmd_help),
                         ("progress", self.cmd_progress), ("story", self.cmd_story),
                         ("eta", self.cmd_eta), ("report", self.cmd_report)]:
            self.app.add_handler(CommandHandler(name, fn, filters=only_owner))
        self.app.add_handler(CallbackQueryHandler(self.on_button))
        self.app.add_handler(MessageHandler(only_owner & filters.TEXT & ~filters.COMMAND, self.on_text))
        self._tasks: list = []

    # --- lifecycle ---
    async def _start(self, app: Application):
        await app.bot.set_my_commands(COMMANDS)  # the "/" menu in the chat
        await self.say(startup_message())
        write_heartbeat("running")
        loop = asyncio.get_running_loop()
        if self.worker:
            self.worker.alert = lambda text: asyncio.run_coroutine_threadsafe(self.say(text), loop)
            self._stop_event = threading.Event()
            self._tasks.append(loop.run_in_executor(None, self.worker.run_forever, self._stop_event))
        self._tasks.append(asyncio.create_task(self.notify_loop()))

    async def _stopping(self, app: Application):
        """Clean stop (systemctl stop/restart, Ctrl+C). A hard WSL shutdown skips this; the next startup
        message then says when the heartbeat stopped."""
        write_heartbeat("clean")
        try:
            await asyncio.wait_for(self.say(f"🔴 ระบบปิด {datetime.now():%H:%M} ({busy_text() or 'ไม่มีงานค้าง'})"), 10)
        except Exception:
            log.exception("could not send the shutdown message")

    async def _stop(self, app: Application):
        if self.worker:
            self._stop_event.set()
        for t in self._tasks:
            t.cancel()

    def run(self):
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

    async def send_video(self, jid: int):
        d = db.job_dir(jid)
        video = d / read_json(jid, "qc.json").get("preview", "final.mp4")
        with open(video, "rb") as f:
            await self.app.bot.send_video(self.owner, f, caption=read_json(jid, "script.json").get("title", "")[:1000],
                                          supports_streaming=True, read_timeout=120, write_timeout=120)

    async def say(self, text: str, **kw):
        return await self.app.bot.send_message(self.owner, text, **kw)

    # --- outgoing: tell the owner whenever a job lands in a status they care about ---
    async def notify_loop(self):
        last_report = asyncio.get_running_loop().time()
        while True:
            try:
                for job in db.pending_notifications(NOTIFY):
                    await self.notify(job)
                    db.update(job["id"], notified_status=job["status"])
                write_heartbeat("running")
                # A story part takes hours on the GPU: report progress every 10 minutes while it is being made.
                if asyncio.get_running_loop().time() - last_report >= PROGRESS_EVERY:
                    last_report = asyncio.get_running_loop().time()
                    for job in db.list_jobs(20):
                        if job["kind"] == "story" and job["status"] == "SCRIPT_APPROVED" and setting("progress_reports"):
                            await self.say("⏱ " + story_progress(job, self.cfg))
            except Exception:
                log.exception("notify failed; will retry")
            await asyncio.sleep(self.cfg["worker"]["poll_seconds"])

    async def notify(self, job):
        jid, st = job["id"], job["status"]
        if st == "AWAITING_SCRIPT_APPROVAL":
            left = MAX_REWRITES - job["revise_count"]
            acts = ["approve"] + (["rewrite"] if left > 0 else []) + ["revise", "cancel"]
            await self.say(script_text(jid) + f"\n\n(เขียนใหม่ได้อีก {left} ครั้ง)", reply_markup=keyboard(jid, acts))
        elif st in ("AWAITING_PUBLISH_APPROVAL", "QC_FAILED"):
            # Both show the video: a failed check (say, 3 seconds too long) is often fine once you've watched it.
            await self.send_video(jid)
            s = read_json(jid, "script.json")
            head = (f"🎬 งาน #{jid} รอยืนยันโพสต์" if st == "AWAITING_PUBLISH_APPROVAL" else
                    f"⚠️ งาน #{jid} ไม่ผ่าน QC — ดูคลิปแล้วตัดสินใจ\nถ้าข้อที่ไม่ผ่านไม่เป็นปัญหา กด \"โพสต์\" ได้เลย")
            await self.say(f"{head}\n\n{s.get('title')}\n\n{s.get('description')}\n\nQC:\n{qc_text(jid)}"
                           f"\n\nจะอัปโหลดเป็น {self.cfg['youtube']['privacy']}",
                           reply_markup=keyboard(jid, ["publish", "redo", "cancel"]))
        elif st == "FAILED":
            await self.say(f"❌ งาน #{jid} ล้มเหลว\n{job['error']}\n\nลองใหม่: /retry {jid}")
        elif st == "PUBLISHED":
            vid = job["youtube_video_id"]
            msg = f"✅ งาน #{jid} อัปโหลดแล้ว\nhttps://youtube.com/shorts/{vid}"
            if self.cfg["youtube"]["privacy"] != "public":
                msg += f"\n\nตอนนี้เป็น {self.cfg['youtube']['privacy']} กดเผยแพร่เองได้ที่:\n{publish.studio_link(vid)}"
            await self.say(msg)

    # --- incoming ---
    async def on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        if q.message.chat.id != self.owner:
            return
        action, jid = q.data.split(":")
        jid = int(jid)
        if action == "revise":
            ok = db.get_job(jid) and db.get_job(jid)["status"] == "AWAITING_SCRIPT_APPROVAL"
            if ok:
                ctx.chat_data["revise_job"] = jid
                await q.answer()
                await q.edit_message_text(q.message.text + "\n\n➡️ แก้ไข: พิมพ์สิ่งที่อยากให้แก้ส่งมาได้เลย")
                return
        else:
            try:
                ok = ACTIONS[action](jid)
            except ValueError as e:
                await q.answer(str(e), show_alert=True)
                return
        if ok:
            await q.answer(LABELS[action])
            await q.edit_message_text(q.message.text + f"\n\n➡️ เลือก: {LABELS[action]}")
        else:  # pressed before, or the job moved on: drop the stale buttons
            await q.answer("ปุ่มนี้ใช้ไปแล้ว", show_alert=True)
            await q.edit_message_reply_markup(None)

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        jid = ctx.chat_data.pop("revise_job", None)
        if jid is None:
            await update.message.reply_text("ยังไม่เข้าใจข้อความนี้ ดูคำสั่งทั้งหมดที่ /help")
            return
        if orch.request_revision(jid, update.message.text):
            await update.message.reply_text(f"รับทราบ กำลังแก้บทงาน #{jid}")
        else:
            await update.message.reply_text(f"งาน #{jid} ไม่ได้รอยืนยันบทแล้ว")

    async def cmd_new(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        topic = " ".join(ctx.args) or None
        try:
            jid = orch.new_job(self.cfg, topic)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        await update.message.reply_text(f"สร้างงาน #{jid} แล้ว {'หัวข้อ: ' + topic if topic else '(ให้ AI เลือกหัวข้อ)'}")

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(HELP)

    async def cmd_story(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        part = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else None
        for f in self.cfg["story"].get("series", []):
            try:
                jid = orch.new_story_job(self.cfg, f, part)
            except ValueError as e:
                if "max_jobs_per_day" in str(e) or part is not None:
                    await update.message.reply_text(str(e))
                    return
                continue
            await update.message.reply_text(f"สร้างงาน #{jid}: {db.get_job(jid)['topic']} เดี๋ยวส่งบทมาให้อนุมัติ")
            return
        await update.message.reply_text("ทุกเรื่องใน story.series มีงานครบทุกตอนแล้ว")

    async def cmd_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(job_list())

    async def cmd_progress(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(story_progress(cfg=self.cfg))

    async def cmd_eta(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(eta.eta_text(self.cfg))

    async def cmd_report(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        arg = (ctx.args[0].lower() if ctx.args else "")
        if arg in ("on", "off"):
            set_setting("progress_reports", arg == "on")
        on = setting("progress_reports")
        await update.message.reply_text(f"รายงานทุก 10 นาที: {'🔔 เปิด' if on else '🔕 ปิด'}"
                                        + ("" if arg in ("on", "off") else "\nเปลี่ยนด้วย /report on หรือ /report off"))

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        jobs = db.list_jobs(10)
        lines = [f"#{j['id']} {STATUS_TH.get(j['status'], j['status'])} — {j['topic'] or '(AI เลือก)'}" for j in jobs]
        await update.message.reply_text("\n".join(lines) or "ยังไม่มีงาน สร้างด้วย /new [หัวข้อ]")

    async def _by_id(self, update, ctx, fn, verb):
        if not ctx.args or not ctx.args[0].isdigit():
            await update.message.reply_text(f"ใช้แบบนี้: /{verb} <เลขงาน>")
            return
        ok = fn(int(ctx.args[0]))
        await update.message.reply_text(f"{verb} งาน #{ctx.args[0]} แล้ว" if ok else f"{verb} งาน #{ctx.args[0]} ไม่ได้ในสถานะนี้")

    async def cmd_cancel(self, update, ctx):
        await self._by_id(update, ctx, orch.cancel, "cancel")

    async def cmd_retry(self, update, ctx):
        await self._by_id(update, ctx, orch.retry, "retry")
