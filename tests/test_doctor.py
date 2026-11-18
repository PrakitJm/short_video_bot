import subprocess

from autovideo import cli
from autovideo.config import SECRET_KEYS


def test_doctor_lists_missing_keys(monkeypatch, capsys):
    for key in SECRET_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cli, "load_config", lambda: {})
    assert cli.doctor(None) == 1
    out = capsys.readouterr().out
    for key in SECRET_KEYS:
        assert key in out


def test_help_runs():
    r = subprocess.run(["autovideo", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "doctor" in r.stdout
