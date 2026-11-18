import json
from pathlib import Path
from string import Template

from autovideo.config import ROOT
from autovideo.models import SCRIPT_SCHEMA, validate_script
from autovideo.providers import LLM


def build_prompts(cfg: dict, topic: str | None, recent_topics) -> tuple[str, str]:
    system = Template((ROOT / "prompts/script_system.md").read_text(encoding="utf-8")).safe_substitute(cfg["channel"])
    if topic:
        prompt = f"เขียนบทวิดีโอหัวข้อ: {topic}"
    else:
        prompt = "คิดหัวข้อใหม่ที่เหมาะกับช่องเอง แล้วเขียนบท ใส่หัวข้อที่เลือกในช่อง topic"
        if recent_topics:
            prompt += "\nห้ามซ้ำกับหัวข้อเหล่านี้:\n" + "\n".join(f"- {t}" for t in recent_topics)
    return system, prompt


def run(job_dir: Path, cfg: dict, llm: LLM, topic: str | None = None, recent_topics: tuple[str, ...] = ()) -> dict:
    out = job_dir / "script.json"
    if out.exists():
        data = json.loads(out.read_text(encoding="utf-8"))
        if not validate_script(data):
            return data

    system, prompt = build_prompts(cfg, topic, recent_topics)
    return _generate(out, cfg, llm, system, prompt)


def revise(job_dir: Path, cfg: dict, llm: LLM, note: str) -> dict:
    """Owner's "แก้ไข": send the current script plus their instruction, keep everything else."""
    out = job_dir / "script.json"
    system, _ = build_prompts(cfg, None, ())
    prompt = Template((ROOT / "prompts/script_revise.md").read_text(encoding="utf-8")).safe_substitute(
        script=out.read_text(encoding="utf-8"), note=note)
    return _generate(out, cfg, llm, system, prompt)


def _generate(out: Path, cfg: dict, llm: LLM, system: str, prompt: str) -> dict:
    problems: list[str] = []
    for _ in range(cfg["limits"]["max_retries"]):
        raw = llm.generate_json(system, prompt, SCRIPT_SCHEMA)
        try:
            data = json.loads(raw)
            problems = validate_script(data)
        except json.JSONDecodeError as e:
            problems = [f"JSON ไม่ถูกต้อง: {e}"]
        if not problems:
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(out)  # atomic: a crash never leaves a half-written script.json
            return data
    raise RuntimeError("บทไม่ผ่าน schema หลังลองครบแล้ว: " + "; ".join(problems))
