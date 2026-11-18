import argparse
import json
import logging
import threading
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from autovideo import db, orchestrator as orch
from autovideo.config import ROOT, SECRET_KEYS, load_config
from autovideo.models import validate_script
from autovideo.providers import get_images, get_llm, get_tts
from autovideo.steps import qc, render, script, visuals, voice

# Config fields the owner must fill in before the pipeline can run.
REQUIRED_CONFIG = [
    ("channel", "niche"),
    ("channel", "tone"),
    ("channel", "audience"),
    ("llm", "model"),
    ("tts", "voice"),
]


def doctor(_args) -> int:
    cfg = load_config()
    problems = []
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            problems.append(f"ไม่พบโปรแกรม {tool} (ติดตั้ง FFmpeg)")
    for key in SECRET_KEYS:
        if not os.getenv(key):
            problems.append(f"ยังไม่ได้ใส่ {key} ใน .env")
    secrets_file = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE")
    if secrets_file and not (ROOT / secrets_file).exists():
        problems.append(f"ไม่พบไฟล์ {secrets_file} (OAuth client ของ YouTube)")
    for section, field in REQUIRED_CONFIG:
        if not (cfg.get(section) or {}).get(field):
            problems.append(f"ยังไม่ได้ตั้งค่า {section}.{field} ใน config.yaml")
    if not (ROOT / "data/youtube_token.json").exists():
        problems.append("ยังไม่ได้เชื่อม YouTube (รัน: uv run autovideo auth youtube)")
    if not any((ROOT / "assets/fonts").glob("*.ttf")):
        problems.append("ไม่มีฟอนต์ .ttf ใน assets/fonts/ (เช่น Kanit หรือ Sarabun)")

    if not problems:
        print("✓ พร้อมใช้งาน ทุกอย่างครบ")
        return 0
    print(f"ขาด {len(problems)} รายการ:")
    for p in problems:
        print(f"  ✗ {p}")
    return 1


def new_job_dir() -> Path:
    # shortcut: timestamp job ids until the jobs table arrives in phase 4.
    return ROOT / "data/jobs" / datetime.now().strftime("%Y%m%d-%H%M%S")


def script_cmd(args) -> int:
    cfg = load_config()
    job_dir = Path(args.job) if args.job else new_job_dir()
    data = script.run(job_dir, cfg, get_llm(cfg, args.dry_run), topic=args.topic)
    print(f"✓ {job_dir / 'script.json'}")
    print(f"  {data['title']} ({len(data['scenes'])} ซีน)")
    return 0


def voice_cmd(args) -> int:
    cfg = load_config()
    job_dir = Path(args.job)
    scenes = voice.run(job_dir, cfg, get_tts(cfg, args.dry_run))
    print(f"✓ เสียง {len(scenes)} ซีน ยาวรวม {sum(s['duration'] for s in scenes):.1f} วินาที")
    print(f"  {job_dir / 'subs.ass'}")
    return 0


def visuals_cmd(args) -> int:
    cfg = load_config()
    credits = visuals.run(Path(args.job), cfg, get_images(cfg, args.dry_run))
    print(f"✓ ภาพ {len(credits)} ซีน (ภาพจริง {sum(1 for c in credits.values() if c)}, พื้นหลังสี {sum(1 for c in credits.values() if not c)})")
    return 0


def render_cmd(args) -> int:
    print(f"✓ {render.run(Path(args.job), load_config())}")
    return 0


def print_qc(result: dict) -> int:
    for name, c in result["checks"].items():
        print(f"  {'✓' if c['ok'] else '✗'} {name}: {c['detail']}")
    print("✓ ผ่าน QC" if result["passed"] else "✗ ไม่ผ่าน QC")
    return 0 if result["passed"] else 1


def qc_cmd(args) -> int:
    return print_qc(qc.run(Path(args.job), load_config()))


def make_cmd(args) -> int:
    """Whole pipeline up to QC, no approvals; the orchestrator (phase 4) replaces this."""
    cfg = load_config()
    job_dir = Path(args.job) if args.job else new_job_dir()
    data = script.run(job_dir, cfg, get_llm(cfg, args.dry_run), topic=args.topic)
    print(f"1/5 บท: {data['title']}")
    scenes = voice.run(job_dir, cfg, get_tts(cfg, args.dry_run))
    print(f"2/5 เสียง: {sum(s['duration'] for s in scenes):.1f} วินาที")
    visuals.run(job_dir, cfg, get_images(cfg, args.dry_run))
    print("3/5 ภาพ: ครบ")
    print(f"4/5 ตัดต่อ: {render.run(job_dir, cfg)}")
    print("5/5 QC:")
    return print_qc(qc.run(job_dir, cfg))


def story_cmd(args) -> int:
    from autovideo.story import run as story  # needs the optional GPU extras (uv sync --extra gpu)
    final = story.run(Path(args.file), args.part, load_config(), draw_only=args.draw_only)
    print(f"✓ ตอนที่ {args.part}: {final}")
    return 0


def story_next_cmd(args) -> int:
    """Queue the next story part (the daily timer runs this)."""
    cfg = load_config()
    files = [args.story] if args.story else cfg["story"].get("series", [])
    for f in files:
        try:
            jid = orch.new_story_job(cfg, f, args.part)
        except ValueError as e:
            print(f"- {f}: {e}")
            if "max_jobs_per_day" in str(e):
                return 1
            continue
        print(f"✓ สร้างงาน #{jid}: {db.get_job(jid)['topic']}")
        return 0
    print("ไม่มีตอนที่ต้องทำ")
    return 0


def new_cmd(args) -> int:
    cfg = load_config()
    if not args.script:
        jid = orch.new_job(cfg, args.topic)
        print(f"✓ สร้างงาน #{jid}")
        return 0
    src = Path(args.script)
    data = json.loads(src.read_text(encoding="utf-8"))
    problems = validate_script(data)
    if problems:
        raise ValueError(f"{src} ไม่ผ่าน schema: " + "; ".join(problems))
    jid = orch.new_job(cfg, data["topic"])
    # A valid script.json makes the script step skip the LLM, so the job goes straight to script approval.
    d = db.job_dir(jid)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, d / "script.json")
    print(f"✓ สร้างงาน #{jid} จาก {src.name}: {data['title']}")
    return 0


def jobs_cmd(args) -> int:
    for j in db.list_jobs(args.limit):
        err = f"  ({j['error'][:80]})" if j["error"] else ""
        print(f"#{j['id']:<4} {j['status']:<26} {j['topic'] or '(AI เลือก)'}{err}")
    return 0


def work_cmd(args) -> int:
    worker = orch.Orchestrator(load_config(), dry_run=args.dry_run)
    if args.once:
        while worker.tick():
            pass
        return 0
    print("ตัวทำงานเริ่มแล้ว กด Ctrl+C เพื่อหยุด")
    try:
        worker.run_forever(threading.Event())
    except KeyboardInterrupt:
        pass
    return 0


def action_cmd(args) -> int:
    fn = {"approve": lambda j: orch.approve_script(j) or orch.approve_publish(j),
          "rewrite": orch.rewrite, "redo": orch.redo_media, "cancel": orch.cancel, "retry": orch.retry}[args.command]
    if args.command == "revise":
        ok = orch.request_revision(args.job_id, args.note)
    else:
        ok = fn(args.job_id)
    job = db.get_job(args.job_id)
    print(f"✓ งาน #{args.job_id} -> {job['status']}" if ok else f"✗ ทำไม่ได้ งาน #{args.job_id} อยู่ในสถานะ {job and job['status']}")
    return 0 if ok else 1


def run_cmd(args) -> int:
    from autovideo.bot.telegram_bot import Bot
    cfg = load_config()
    token, owner = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_OWNER_CHAT_ID")
    if not token or not owner:
        raise ValueError("ยังไม่ได้ใส่ TELEGRAM_BOT_TOKEN หรือ TELEGRAM_OWNER_CHAT_ID ใน .env")
    print("ระบบเริ่มแล้ว (bot + ตัวทำงาน) กด Ctrl+C เพื่อหยุด")
    Bot(cfg, token, int(owner), orch.Orchestrator(cfg, dry_run=args.dry_run)).run()
    return 0


def auth_cmd(args) -> int:
    from autovideo.providers.upload_youtube import authorize
    print(f"✓ บันทึก token ที่ {authorize()}")
    return 0


def setup_logging() -> None:
    (ROOT / "data/logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("autovideo")
    log.setLevel(logging.INFO)
    file = logging.FileHandler(ROOT / "data/logs/autovideo.log", encoding="utf-8")
    file.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("! %(message)s"))
    console.setLevel(logging.WARNING)
    log.addHandler(file)
    log.addHandler(console)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(prog="autovideo", description="ระบบผลิตและโพสต์วิดีโอสั้นอัตโนมัติ")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="ตรวจว่ามี FFmpeg, คีย์ และค่า config ครบหรือไม่").set_defaults(func=doctor)
    p = sub.add_parser("script", help="เขียนบทเป็น script.json")
    p.add_argument("--topic", help="หัวข้อคลิป (ไม่ใส่ให้ AI คิดเอง)")
    p.add_argument("--job", help="โฟลเดอร์งานเดิมที่จะทำต่อ")
    p.add_argument("--dry-run", action="store_true", help="ใช้ตัวปลอม ไม่เรียกบริการจริง")
    p.set_defaults(func=script_cmd)
    p = sub.add_parser("voice", help="สร้างเสียงพากย์ทีละซีนและไฟล์ซับ subs.ass")
    p.add_argument("--job", required=True, help="โฟลเดอร์งานที่มี script.json")
    p.add_argument("--dry-run", action="store_true", help="ใช้เสียงเงียบแทน ไม่เรียก edge-tts")
    p.set_defaults(func=voice_cmd)
    for name, func, help_ in [("visuals", visuals_cmd, "หาภาพทีละซีนจาก Pixabay"),
                              ("render", render_cmd, "ตัดต่อเป็น final.mp4"),
                              ("qc", qc_cmd, "ตรวจ final.mp4 อัตโนมัติ")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--job", required=True, help="โฟลเดอร์งาน")
        if name == "visuals":
            p.add_argument("--dry-run", action="store_true", help="ไม่เรียก Pixabay ใช้พื้นหลังสี")
        p.set_defaults(func=func)
    p = sub.add_parser("make", help="ทำทั้งสายตั้งแต่บทจนผ่าน QC")
    p.add_argument("--topic", help="หัวข้อคลิป (ไม่ใส่ให้ AI คิดเอง)")
    p.add_argument("--job", help="โฟลเดอร์งานเดิมที่จะทำต่อ")
    p.add_argument("--dry-run", action="store_true", help="ใช้ตัวปลอมทั้งหมด ไม่เรียกบริการจริง")
    p.set_defaults(func=make_cmd)

    p = sub.add_parser("story", help="ทำนิทาน 1 ตอนด้วยภาพ AI บนเครื่อง (ต้องมีการ์ดจอ)")
    p.add_argument("file", help="ไฟล์เรื่อง เช่น drafts/stories/khao_phan.json")
    p.add_argument("--part", type=int, required=True, help="ตอนที่")
    p.add_argument("--draw-only", action="store_true", help="หยุดหลังวาดภาพ เพื่อเลือกภาพก่อนทำให้ขยับ")
    p.set_defaults(func=story_cmd)

    p = sub.add_parser("story-next", help="ใส่นิทานตอนถัดไปลงคิว (บอทจะส่งบทมาให้อนุมัติ)")
    p.add_argument("--story", help="ไฟล์เรื่อง (ไม่ใส่ = ตาม story.series ใน config)")
    p.add_argument("--part", type=int, help="ตอนที่ (ไม่ใส่ = ตอนถัดไปที่ยังไม่มีงาน)")
    p.set_defaults(func=story_next_cmd)

    p = sub.add_parser("new", help="สร้างงานใหม่ในคิว (ใช้กับ cron)")
    p.add_argument("--topic", help="หัวข้อคลิป (ไม่ใส่ให้ AI คิดเอง)")
    p.add_argument("--script", help="ใช้บทที่เขียนไว้แล้ว เช่น drafts/honey.json (ไม่เรียก AI)")
    p.set_defaults(func=new_cmd)
    p = sub.add_parser("jobs", help="ดูงานล่าสุดและสถานะ")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=jobs_cmd)
    p = sub.add_parser("work", help="รันตัวทำงานอย่างเดียว ไม่มี Telegram")
    p.add_argument("--once", action="store_true", help="ทำจนไม่มีงานให้ทำแล้วหยุด")
    p.add_argument("--dry-run", action="store_true", help="ใช้ตัวปลอมทั้งหมด")
    p.set_defaults(func=work_cmd)
    for name, help_ in [("approve", "อนุมัติบท หรืออนุมัติโพสต์ แล้วแต่งานรออะไรอยู่"), ("rewrite", "ให้ AI เขียนบทใหม่"),
                        ("revise", "สั่งแก้บท"), ("redo", "ทำเสียงและภาพใหม่"), ("cancel", "ยกเลิกงาน"),
                        ("retry", "ลองงานที่ล้มเหลวใหม่")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("job_id", type=int)
        if name == "revise":
            p.add_argument("note", help="สิ่งที่อยากให้แก้")
        p.set_defaults(func=action_cmd)
    p = sub.add_parser("run", help="เปิดระบบเต็ม: Telegram bot + ตัวทำงาน")
    p.add_argument("--dry-run", action="store_true", help="ใช้ตัวปลอมทั้งหมด (ไม่โพสต์จริง)")
    p.set_defaults(func=run_cmd)
    p = sub.add_parser("auth", help="เชื่อมบัญชี (ครั้งเดียว)")
    p.add_argument("service", choices=["youtube"])
    p.set_defaults(func=auth_cmd)
    args = parser.parse_args()
    try:
        sys.exit(args.func(args))
    except (ValueError, RuntimeError) as e:
        sys.exit(f"✗ {e}")


if __name__ == "__main__":
    main()
