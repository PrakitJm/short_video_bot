import json
import shutil
from pathlib import Path

import pytest
from pythainlp.tokenize import word_tokenize

from autovideo import media, subtitles
from autovideo.config import load_config
from autovideo.steps import voice

CFG = load_config()
FIXTURE = Path(__file__).parent / "fixtures/script_sleep.json"
NARRATIONS = [s["narration"] for s in json.loads(FIXTURE.read_text(encoding="utf-8"))["scenes"]]


@pytest.mark.parametrize("text", NARRATIONS + ["ข้อความสั้น", "ประเทศไทยมีจังหวัดทั้งหมดเจ็ดสิบเจ็ดจังหวัดรวมกรุงเทพมหานคร"])
def test_lines_never_split_inside_a_word(text):
    lines = subtitles.split_lines(text)
    tokens = word_tokenize(text, engine="newmm", keep_whitespace=True)
    word_edges, pos = {0, len(text)}, 0
    for t in tokens:
        pos += len(t)
        word_edges.add(pos)
    for off, line in lines:
        assert text[off:off + len(line)] == line
        assert off in word_edges and off + len(line) in word_edges
        # Over the limit only when a single word is itself that long.
        assert subtitles.visible_len(line) <= 20 or len(word_tokenize(line, engine="newmm")) == 1
    assert "".join(l for _, l in lines).replace(" ", "") == text.replace(" ", "")


def test_visible_len_ignores_thai_marks():
    assert subtitles.visible_len("ที่นี่") == 2  # ท and น; the marks take no width


def test_timed_lines_are_ordered_and_cover_audio():
    text = NARRATIONS[0]
    words = [{"text": t, "start": i * 0.25, "end": (i + 1) * 0.25}
             for i, t in enumerate(word_tokenize(text, engine="newmm", keep_whitespace=False))]
    events = subtitles.timed_lines(text, words, duration=9.0)
    assert events[0][0] == 0.0 and events[-1][1] == 9.0
    for (s1, e1, _), (s2, _, _) in zip(events, events[1:]):
        assert s1 < e1 == s2


class StubTTS:
    def __init__(self):
        self.calls = 0

    def synthesize(self, text, out):
        self.calls += 1
        out.write_bytes(b"mp3")
        return [{"text": text[:3], "start": 0.0, "end": 0.5}]


@pytest.fixture
def job(tmp_path, monkeypatch):
    shutil.copy(FIXTURE, tmp_path / "script.json")
    monkeypatch.setattr(media, "duration", lambda p: 5.0)
    return tmp_path


def test_voice_writes_every_scene_and_subs(job):
    tts = StubTTS()
    scenes = voice.run(job, CFG, tts)
    assert tts.calls == len(NARRATIONS) == len(scenes)
    assert all((job / f"audio/scene_{i:02d}.mp3").exists() for i in range(1, 8))
    assert (job / "subs.ass").read_text(encoding="utf-8").count("Dialogue:") >= len(NARRATIONS)
    voice.run(job, CFG, tts)  # second run reuses finished scenes
    assert tts.calls == len(NARRATIONS)


def test_voice_fails_when_too_long(job, monkeypatch):
    monkeypatch.setattr(media, "duration", lambda p: 20.0)
    with pytest.raises(RuntimeError, match="max_seconds"):
        voice.run(job, CFG, StubTTS())
