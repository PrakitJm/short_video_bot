import json
import shutil
from pathlib import Path

import numpy as np
import pytest

STORY = Path(__file__).parent.parent / "drafts/stories/khao_phan.json"
STORIES = sorted((Path(__file__).parent.parent / "drafts/stories").glob("*.json"))
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")


@pytest.mark.parametrize("path", STORIES, ids=lambda p: p.stem)
def test_story_file_is_consistent(path):
    s = json.loads(path.read_text(encoding="utf-8"))
    for part in s["parts"]:
        assert [x["id"] for x in part["shots"]] == list(range(1, len(part["shots"]) + 1))
        for x in part["shots"]:
            assert x["image_prompt"].isascii() and x["narration"].strip()
            assert set(x["characters"]) <= set(s["characters"]) and x["motion"] in ("ai", "parallax")


def test_part_becomes_a_normal_script():
    from autovideo.story.run import part_script
    s = json.loads(STORY.read_text(encoding="utf-8"))
    sc = part_script(s, s["parts"][0])
    assert sc["title"].startswith("ข้าวพันธุ์ของพ่อ ตอนที่ 1/3") and len(sc["title"]) <= 70
    assert len(sc["scenes"]) == 18 and "AI" in sc["description"]


@needs_ffmpeg
def test_parallax_clip_has_right_length(tmp_path):
    pytest.importorskip("cv2")
    from autovideo import media
    from autovideo.story.parallax import render
    img = (np.random.default_rng(0).random((64, 36, 3)) * 255).astype(np.uint8)
    depth = np.tile(np.linspace(0, 1, 64, dtype=np.float32)[:, None], (1, 36))
    render(img, depth, tmp_path / "p.mp4", 1.0, 30, 1, 36, 64)
    assert int(media.probe(tmp_path / "p.mp4")["streams"][0]["nb_frames"]) == 30


def test_part_count_includes_outlined_parts():
    from autovideo.story.run import part_script
    s = json.loads((STORY.parent / "system_loop.json").read_text(encoding="utf-8"))
    assert part_script(s, s["parts"][0])["title"].startswith("ระบบย้อนเวลา 99 ครั้ง ตอนที่ 1/12")


# --- story jobs in the queue (no GPU: the video step is stubbed) ---

def llm_part(n_shots=16):
    return json.dumps({"title": "ถ้ำก็อบลิน", "shots": [
        {"narration": f"ช็อตที่ {i}", "image_prompt": "a goblin cave, torches", "characters": ["ton"] if i % 2 else [],
         "motion": "ai" if i <= 6 else "parallax"} for i in range(1, n_shots + 1)]}, ensure_ascii=False)


@pytest.fixture
def story_env(tmp_path, monkeypatch):
    from autovideo import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db, "JOBS_DIR", tmp_path / "jobs")
    path = tmp_path / "s.json"
    s = json.loads((STORY.parent / "system_loop.json").read_text(encoding="utf-8"))
    s["parts"] = [p for p in s["parts"] if p["part"] <= 3]  # parts 4+ only outlined, as for a new series
    path.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return path


def test_llm_writes_missing_part_and_saves_it(story_env):
    from autovideo.providers.fakes import FakeLLM
    from autovideo.story.write import write_part
    llm = FakeLLM([json.dumps({"title": "x", "shots": []}), llm_part()])  # first answer is invalid
    part = write_part(story_env, 4, llm)
    saved = json.loads(story_env.read_text(encoding="utf-8"))
    assert part["part"] == 4 and len(part["shots"]) == 16 and part["shots"][0]["id"] == 1
    assert [p["part"] for p in saved["parts"]] == [1, 2, 3, 4]
    assert "ถ้ำก็อบลิน" in llm.calls[0] and "อาจารย์ตาเดียว" not in llm.calls[0].split("ตอนก่อนหน้า")[0][-50:]
    assert "รอบก่อนผิด" in llm.calls[1]


def test_story_job_goes_through_both_approvals(story_env, monkeypatch):
    from autovideo import db, orchestrator as orch
    from autovideo.config import load_config
    from autovideo.providers import fakes
    from autovideo.story import run as story_run
    from autovideo.steps import qc
    cfg = load_config()
    llm = fakes.FakeLLM([llm_part()])
    monkeypatch.setattr(orch, "get_llm", lambda c, dry: llm)
    made = []
    monkeypatch.setattr(story_run, "run", lambda path, part, c, **kw: made.append((part, kw)) or kw["out_dir"] / "final.mp4")
    qc_limits = []
    monkeypatch.setattr(qc, "run", lambda d, c: qc_limits.append(c["video"]["max_seconds"]) or {"passed": True, "checks": {}})
    w = orch.Orchestrator(cfg, dry_run=True)

    def drain():
        while w.tick():
            pass

    first = orch.new_story_job(cfg, str(story_env))
    assert db.get_job(first)["part"] == 1
    drain()
    assert db.get_job(first)["status"] == "AWAITING_SCRIPT_APPROVAL" and llm.calls == []  # part 1 is hand-written
    sc = json.loads((db.job_dir(first) / "script.json").read_text())
    assert len(sc["scenes"]) == 18 and sc["category_id"] == "24"
    orch.approve_script(first)
    drain()
    assert db.get_job(first)["status"] == "AWAITING_PUBLISH_APPROVAL" and made[0][0] == 1
    assert qc_limits == [cfg["story"]["max_seconds"]]  # stories are checked against the 90 s story limit
    assert orch.redo_media(first)
    drain()
    assert made[1][1]["seed_offset"] == 1000  # "ทำใหม่" draws with new seeds

    for _ in range(2):  # parts 2 and 3 tomorrow; then part 4 has only an outline
        db.update(first, created_at="2000-01-01T00:00:00")
        cfg["limits"]["max_jobs_per_day"] = 99
        orch.new_story_job(cfg, str(story_env))
    fourth = orch.new_story_job(cfg, str(story_env))
    assert db.get_job(fourth)["part"] == 4
    drain()
    assert db.get_job(fourth)["status"] == "AWAITING_SCRIPT_APPROVAL" and len(llm.calls) == 1
    with pytest.raises(ValueError, match="มีงานอยู่แล้ว"):
        orch.new_story_job(cfg, str(story_env), part=4)


def test_judge_picks_story_match_and_asks_redraw(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    from autovideo.story import judge
    (tmp_path / "shots").mkdir()
    for sid in (1, 2):
        for k in range(3):
            (tmp_path / "shots" / f"shot_{sid:02d}.c{k}.png").write_bytes(b"png")
    answers = {1: [(3, 9), (8, 7), (5, 9)], 2: [(2, 9), (4, 9), (5, 8)]}  # (match, quality) per take

    class Models:
        def generate_content(self, model, contents, config):
            sid = 1 if "หนึ่ง" in contents[-1] else 2
            return NS(text=json.dumps({"images": [{"match": m, "quality": q, "problem": "-"} for m, q in answers[sid]],
                                       "better_prompt": "1boy, solo, better", "motion": f"motion {sid}"}))
    monkeypatch.setattr(judge, "client", lambda: NS(models=Models()))
    monkeypatch.setattr("google.genai.types.Part.from_bytes", lambda data, mime_type: data, raising=False)
    shots = [{"id": 1, "narration": "ช็อตหนึ่ง", "image_prompt": "a", "characters": []},
             {"id": 2, "narration": "ช็อตสอง", "image_prompt": "b", "characters": []}]
    redo = judge.run(tmp_path, shots, {"characters": {}}, {"llm": {"model": "m"}}, 3, final=False)
    assert (tmp_path / "shots/shot_01.png").exists()  # take 1 matches the story best
    assert json.loads((tmp_path / "judge.json").read_text())["shot_01.png"]["best"] == 1
    assert [s["id"] for s in redo] == [2] and redo[0]["image_prompt"] == "1boy, solo, better"
    assert not (tmp_path / "shots/shot_02.png").exists() and judge.motion(tmp_path, 1) == "motion 1"
