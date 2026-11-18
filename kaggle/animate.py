"""Kaggle GPU notebook: image-to-video with Wan 2.2 TI2V-5B for every shot in the attached dataset.

Input  /kaggle/input/autovideo-shots/{jobs.json, *.png}   jobs: [{name, image, prompt, frames, steps}]
Output /kaggle/working/clips/<name>.mp4 and /kaggle/working/report.json (timings, GPU, problems)."""
import glob
import json
import os
import subprocess
import sys
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
T0 = time.time()
report = {"started": T0, "shots": {}, "errors": []}
OUT = "/kaggle/working"
os.makedirs(f"{OUT}/clips", exist_ok=True)


def save():
    report["elapsed_s"] = round(time.time() - T0)
    json.dump(report, open(f"{OUT}/report.json", "w"), indent=1)


subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.35", "transformers", "accelerate",
                "ftfy", "imageio", "imageio-ffmpeg"], check=True)
import numpy as np  # noqa: E402
import torch  # noqa: E402
from diffusers import AutoencoderKLWan, WanImageToVideoPipeline  # noqa: E402
from diffusers.utils import export_to_video, load_image  # noqa: E402

report["gpu"] = torch.cuda.get_device_name(0)
# T4 (sm 7.5) reports bf16 "supported" but only emulates it, which is very slow: use fp16 below sm 8.0.
report["capability"] = ".".join(map(str, torch.cuda.get_device_capability(0)))
DTYPE = torch.bfloat16 if torch.cuda.get_device_capability(0) >= (8, 0) else torch.float16
report["dtype"] = str(DTYPE)
src = next(d for d in glob.glob("/kaggle/input/**/jobs.json", recursive=True))
IN = os.path.dirname(src)
jobs = json.load(open(src))
NEG = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，"
       "多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")

import gc  # noqa: E402
import traceback  # noqa: E402

report["gpus"] = torch.cuda.device_count()
t = time.time()
MODEL = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
vae = AutoencoderKLWan.from_pretrained(MODEL, subfolder="vae", torch_dtype=torch.float32)
vae.enable_tiling()  # encoding/decoding 720p video in one piece does not fit 15 GB
pipe = WanImageToVideoPipeline.from_pretrained(MODEL, vae=vae, torch_dtype=DTYPE)
report["load_s"] = round(time.time() - t)

# The umT5-XXL text encoder alone is ~11 GB: embed every prompt first, then drop it before making video.
t = time.time()
pipe.text_encoder.to("cuda")
embeds = {}
with torch.no_grad():
    for j in jobs:
        pe, ne = pipe.encode_prompt(prompt=j["prompt"], negative_prompt=NEG, do_classifier_free_guidance=True,
                                    device="cuda")
        embeds[j["name"]] = (pe.cpu(), ne.cpu())
pipe.text_encoder = None
gc.collect()
torch.cuda.empty_cache()
# Store the 5B transformer's weights as fp8 (~5 GB instead of ~10 GB) and compute each layer in fp16:
# fp16 weights + activations overflow the T4's 15 GB at step 0.
pipe.transformer.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=DTYPE)
pipe.enable_model_cpu_offload()
report["encode_s"] = round(time.time() - t)
save()

# Try the full size first; on out-of-memory fall back to fewer frames, then to 480p.
SIZES = [(1280, 704, None), (1280, 704, 81), (832, 480, None)]

for j in jobs:
    out = f"{OUT}/clips/{j['name']}.mp4"
    if os.path.exists(out):
        continue
    for h, w, frames_cap in SIZES:
        steps_t = []

        def tick(p, i, ts, kw):
            steps_t.append(time.time())
            return kw
        n = min(j.get("frames", 121), frames_cap or 999)
        try:
            t = time.time()
            torch.cuda.reset_peak_memory_stats()
            pe, ne = embeds[j["name"]]
            image = load_image(os.path.join(IN, j["image"])).convert("RGB").resize((w, h))
            frames = pipe(image=image, prompt_embeds=pe.to("cuda"), negative_prompt_embeds=ne.to("cuda"),
                          height=h, width=w, num_frames=n, num_inference_steps=j.get("steps", 30),
                          guidance_scale=5.0, callback_on_step_end=tick,
                          generator=torch.Generator("cpu").manual_seed(j.get("seed", 0))).frames[0]
            arr = np.asarray(frames)
            export_to_video(frames, out, fps=24)
            report["shots"][j["name"]] = {
                "size": f"{w}x{h}", "seconds": round(time.time() - t), "frames": len(frames),
                "sec_per_step": round(float(np.median(np.diff(steps_t))), 1) if len(steps_t) > 1 else None,
                "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1),
                "mean_pixel": round(float(arr.mean()), 3), "nan_or_black": bool(np.isnan(arr).any() or arr.max() < 0.02)}
            break
        except torch.cuda.OutOfMemoryError:
            report["errors"].append(f"{j['name']} {w}x{h}x{n}: OOM at step {len(steps_t)}\n" + traceback.format_exc()[-1500:])
            gc.collect()
            torch.cuda.empty_cache()
        except Exception:  # keep going with the next shot; the caller falls back for this one
            report["errors"].append(f"{j['name']}: " + traceback.format_exc()[-1500:])
            break
        finally:
            save()
save()
