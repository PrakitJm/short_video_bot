"""Laptop GPU care: pause between images/clips while the GPU is too hot (it throttles to ~15% anyway)."""
import subprocess
import time


def temperature() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def cool_down(hot: int = 85, ok: int = 75, max_wait: int = 900) -> None:
    t = temperature()
    if t is None or t < hot:
        return
    print(f"GPU {t}°C: cooling down to {ok}°C", flush=True)
    end = time.time() + max_wait
    while time.time() < end and (temperature() or 0) > ok:
        time.sleep(15)
