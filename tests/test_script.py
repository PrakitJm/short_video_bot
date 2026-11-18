import copy
import json

import pytest

from autovideo.config import load_config
from autovideo.models import validate_script
from autovideo.providers.fakes import FakeLLM, sample_script
from autovideo.steps import script

CFG = load_config()


def test_sample_script_is_valid():
    assert validate_script(sample_script()) == []


@pytest.mark.parametrize(
    "mutate, expect",
    [
        (lambda d: d["scenes"].pop(), "scenes"),                      # only 4 scenes
        (lambda d: d.update(title="ก" * 71), "title"),                # title too long
        (lambda d: d.pop("tags"), "tags"),                            # missing field
        (lambda d: d["scenes"][0].update(visual_query="ภูเขา"), "ภาษาอังกฤษ"),
        (lambda d: d["scenes"][1].update(id=9), "id"),
    ],
)
def test_invalid_scripts_rejected(mutate, expect):
    d = copy.deepcopy(sample_script())
    mutate(d)
    problems = validate_script(d)
    assert problems and any(expect in p for p in problems)


def test_retries_until_valid(tmp_path):
    bad = json.dumps({"topic": "x"})
    llm = FakeLLM([ "not json", bad, json.dumps(sample_script("แมว"), ensure_ascii=False)])
    data = script.run(tmp_path, CFG, llm, topic="แมว")
    assert data["topic"] == "แมว" and len(llm.calls) == 3
    assert json.loads((tmp_path / "script.json").read_text(encoding="utf-8")) == data


def test_fails_after_max_retries(tmp_path):
    llm = FakeLLM(["{}"] * 10)
    with pytest.raises(RuntimeError, match="schema"):
        script.run(tmp_path, CFG, llm, topic="แมว")
    assert not (tmp_path / "script.json").exists()


def test_skips_when_valid_script_exists(tmp_path):
    script.run(tmp_path, CFG, FakeLLM(), topic="แมว")
    llm = FakeLLM()
    script.run(tmp_path, CFG, llm, topic="แมว")
    assert llm.calls == []


def test_prompt_avoids_recent_topics():
    _, prompt = script.build_prompts(CFG, None, ["หัวข้อเก่า"])
    assert "หัวข้อเก่า" in prompt
