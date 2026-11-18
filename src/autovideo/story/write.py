"""Have the LLM write one part of a story series from its outline, in the same shape as hand-written parts.

The story file keeps everything the model needs to stay consistent: characters (ids + looks), style,
the outline of every part, and the parts written so far (the previous part is sent in full)."""
import json
import logging
from pathlib import Path

from autovideo.providers import LLM

log = logging.getLogger("autovideo")
SHOTS = (15, 20)
AI_SHOTS = 6

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "shots": {
            "type": "array", "minItems": SHOTS[0], "maxItems": SHOTS[1],
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "characters": {"type": "array", "items": {"type": "string"}},
                    "motion": {"type": "string", "enum": ["ai", "parallax"]},
                },
                "required": ["narration", "image_prompt", "characters", "motion"],
            },
        },
    },
    "required": ["title", "shots"],
}

SYSTEM = """คุณเป็นนักเขียนบทคลิปสั้นแนวเรื่องเล่าต่อเนื่องเป็นตอน ภาษาไทย อ่านโดยเสียง AI
กฎ:
- ตอนละ {lo}-{hi} ช็อต ความยาวรวมคำบรรยายประมาณ 550 ตัวอักษร (อ่านจบใน 55-65 วินาที) แต่ละช็อตยาวไม่เกิน 45 ตัวอักษร
- ช็อตแรกขึ้นต้นว่า "ตอนที่แล้ว" แล้วสรุปตอนก่อนใน 1 ประโยค (ยกเว้นตอนที่ 1)
- ช็อตสุดท้ายจบแบบค้างให้อยากดูต่อ แล้วลงท้ายว่า "ติดตามตอนต่อไป" (ยกเว้นตอนสุดท้ายของเรื่อง ให้จบอย่างมีพลัง)
- เขียนตัวเลขเป็นคำอ่าน เช่น "เก้าสิบแปด" ไม่ใช้เลขอารบิก ไม่ใช้อีโมจิ ไม่ใช้วงเล็บ
- image_prompt เป็นภาษาอังกฤษล้วน บรรยายฉาก ท่าทาง สีหน้า แสง ในภาพเดียว (single scene) ไม่เกิน 25 คำ
  ห้ามบรรยายหน้าตาตัวละครใน image_prompt (ระบบใส่ให้เอง) ให้ใส่แค่การกระทำ
  ถ้าไม่มีคนในภาพ ให้ลงท้ายด้วย "no humans"
- characters คือ id ของตัวละครที่อยู่ในภาพ เลือกจาก: {ids} ตัวหลักของช็อตต้องอยู่ตัวแรก เว้นว่างได้ถ้าไม่มีคน
- motion: ให้ "ai" กับ {ai} ช็อตที่มีการเคลื่อนไหวสำคัญที่สุดของตอน ที่เหลือ "parallax"
- ทำตามโครงเรื่องของตอนนี้ให้ครบ และต้องต่อเนื่องกับตอนก่อนหน้า"""


def build_prompt(story: dict, part_no: int, note: str | None = None) -> str:
    chars = "\n".join(f"- {k}: {v['look']}" for k, v in story["characters"].items())
    outline = "\n".join(f"ตอนที่ {o['part']} {o['title']}: {o['summary']}" for o in story.get("outline", []))
    written = {p["part"]: p for p in story["parts"]}
    prev = written.get(part_no - 1)
    prev_text = ("\n".join(s["narration"] for s in prev["shots"])) if prev else "(ไม่มี)"
    me = next((o for o in story.get("outline", []) if o["part"] == part_no), None)
    last = max(p["part"] for p in story["parts"] + story.get("outline", []))
    out = (f"เรื่อง: {story['series']} (ทั้งหมด {last} ตอน)\n\nตัวละคร:\n{chars}\n\nโครงเรื่องทุกตอน:\n{outline}\n\n"
           f"คำบรรยายของตอนที่ {part_no - 1} (ตอนก่อนหน้า):\n{prev_text}\n\n"
           f"เขียนตอนที่ {part_no}" + (f" ชื่อตอน \"{me['title']}\" ตามโครง: {me['summary']}" if me else "")
           + (" (นี่คือตอนสุดท้าย)" if part_no == last else ""))
    if note:
        out += f"\n\nแก้ไขตามที่เจ้าของช่องขอ: {note}"
    return out


def validate(part: dict, story: dict) -> list[str]:
    errs = []
    ids = set(story["characters"])
    if not SHOTS[0] <= len(part.get("shots", [])) <= SHOTS[1]:
        errs.append(f"ต้องมี {SHOTS[0]}-{SHOTS[1]} ช็อต")
    for i, s in enumerate(part.get("shots", []), 1):
        if not s["narration"].strip():
            errs.append(f"ช็อต {i} ไม่มีคำบรรยาย")
        if not s["image_prompt"].isascii():
            errs.append(f"ช็อต {i} image_prompt ต้องเป็นภาษาอังกฤษ")
        if set(s["characters"]) - ids:
            errs.append(f"ช็อต {i} มีตัวละครที่ไม่รู้จัก {set(s['characters']) - ids}")
    return errs


def write_part(story_path: Path, part_no: int, llm: LLM, retries: int = 3, note: str | None = None) -> dict:
    """Write (or rewrite) part `part_no` and save it into the story file. Returns the part."""
    story = json.loads(story_path.read_text(encoding="utf-8"))
    system = SYSTEM.format(lo=SHOTS[0], hi=SHOTS[1], ids=", ".join(story["characters"]), ai=AI_SHOTS)
    prompt, errs = build_prompt(story, part_no, note), []
    for attempt in range(retries):
        raw = llm.generate_json(system, prompt + (f"\n\nรอบก่อนผิด: {'; '.join(errs)}" if errs else ""), SCHEMA)
        try:
            part = json.loads(raw)
        except json.JSONDecodeError as e:
            errs = [f"JSON เสีย: {e}"]
            continue
        errs = validate(part, story)
        if not errs:
            break
        log.warning("story part %s attempt %s: %s", part_no, attempt + 1, errs)
    else:
        raise ValueError(f"เขียนตอนที่ {part_no} ไม่ผ่าน {retries} รอบ: {'; '.join(errs)}")
    part = {"part": part_no, "title": part["title"], "written_by": "llm",
            "shots": [{"id": i, **s} for i, s in enumerate(part["shots"], 1)]}
    story["parts"] = sorted([p for p in story["parts"] if p["part"] != part_no] + [part], key=lambda p: p["part"])
    tmp = story_path.with_suffix(".tmp.json")
    tmp.write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(story_path)
    return part
