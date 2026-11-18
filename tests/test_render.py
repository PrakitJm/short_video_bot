import json
import shutil
from pathlib import Path

import pytest

from autovideo.config import load_config
from autovideo.providers.fakes import FakeImages
from autovideo.steps import qc, render, visuals

CFG = load_config()
FIXTURE = Path(__file__).parent / "fixtures/script_sleep.json"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")


def test_scene_frames_do_not_drift():
    durs = [1.234] * 30
    frames = render.scene_frames(durs, 30)
    assert sum(frames) == round(sum(durs) * 30)
    assert max(frames) - min(frames) <= 1


class PickyImages:
    """Returns the same two photo ids for every query, then fails."""
    def __init__(self):
        self.calls = 0

    def fetch(self, query, out, exclude):
        self.calls += 1
        if self.calls == 3:
            raise ConnectionError("network down")
        pid = next((p for p in ["a", "b"] if p not in exclude), None)
        if pid is None:
            return None
        out.write_bytes(b"jpg")
        return {"id": pid, "photographer": "X", "url": "https://example.com"}


@needs_ffmpeg
def test_visuals_never_reuses_and_falls_back(tmp_path):
    shutil.copy(FIXTURE, tmp_path / "script.json")
    credits = visuals.run(tmp_path, CFG, PickyImages())
    ids = [c["id"] for c in credits.values() if c]
    assert ids == ["a", "b"]  # no duplicates, the rest used colour backgrounds
    assert len(credits) == 7 and all((tmp_path / f"images/scene_{i:02d}.jpg").exists() for i in range(1, 8))
    assert json.loads((tmp_path / "credits.json").read_text())["1"]["id"] == "a"


@needs_ffmpeg
def test_dry_run_pipeline_passes_qc(tmp_path):
    from autovideo.providers.fakes import FakeLLM, FakeTTS
    from autovideo.steps import script, voice
    script.run(tmp_path, CFG, FakeLLM(), topic="x")
    voice.run(tmp_path, CFG, FakeTTS())
    visuals.run(tmp_path, CFG, FakeImages())
    render.run(tmp_path, CFG)
    result = qc.run(tmp_path, CFG)
    assert result["passed"], result
    # Too-short limits must flip the duration check.
    strict = {**CFG, "video": {**CFG["video"], "min_seconds": 50}}
    assert not qc.check(tmp_path / "final.mp4", strict)["checks"]["duration"]["ok"]


@needs_ffmpeg
def test_landscape_clip_becomes_portrait_and_loops(tmp_path):
    from autovideo import media
    src = tmp_path / "clip.mp4"  # 1 s landscape clip, scene needs 2 s
    media.ffmpeg("-f", "lavfi", "-i", "testsrc=s=1920x1080:d=1:r=25", "-pix_fmt", "yuv420p", str(src))
    out = tmp_path / "out.mp4"
    render.render_clip(src, out, 60, CFG)
    s = media.probe(out)["streams"][0]
    assert (s["width"], s["height"], int(s["nb_frames"])) == (1080, 1920, 60)


def test_music_pick_is_remembered(tmp_path):
    first = render.pick_music(tmp_path)
    assert render.pick_music(tmp_path) == first  # resume keeps the same track
    saved = json.loads((tmp_path / "music.json").read_text())
    assert saved["file"] == (first.name if first else None)


def test_music_credit_goes_in_description():
    from autovideo.providers.fakes import sample_script
    from autovideo.steps import publish
    meta = publish.build_meta(sample_script(), {}, CFG, '"Carefree" Kevin MacLeod (incompetech.com)')
    assert "เพลง: \"Carefree\" Kevin MacLeod" in meta["snippet"]["description"]


def test_pixabay_video_skips_used_clips(tmp_path, monkeypatch):
    from autovideo.providers import images_pixabay
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    v = {"url": "u", "width": 1920, "height": 1080, "size": 1}
    hits = {"hits": [{"id": n, "user": "U", "pageURL": f"p{n}", "tags": "q", "videos": {"large": v, "tiny": v}}
                     for n in (1, 2)]}
    px = images_pixabay.PixabayImages()
    monkeypatch.setattr(px, "_get", lambda url: json.dumps(hits).encode() if "api" in url else b"mp4")
    assert px.fetch_video("q", tmp_path / "a.mp4", {"v1"})["id"] == "v2"


def test_pixabay_keeps_only_hits_whose_tags_match():
    from autovideo.providers.images_pixabay import relevant
    hits = [{"id": 1, "tags": "lizard, reptile"}, {"id": 2, "tags": "ocean, water"},
            {"id": 3, "tags": "deep, blue, ocean, water"}]
    assert [h["id"] for h in relevant(hits, "deep blue ocean water", set())] == [3, 2]
    assert relevant(hits, "octopus", set()) == []
    assert [h["id"] for h in relevant(hits, "deep blue ocean water", {"v3"}, prefix="v")] == [2]
