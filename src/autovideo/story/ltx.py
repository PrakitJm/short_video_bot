"""Image-to-video with LTX-Video 2B distilled (8 steps) on a 6 GB GPU, for the shots marked motion: ai.

Two separate processes so the 19 GB T5 text encoder and the video model are never in memory together:
  python -m autovideo.story.ltx encode <part_dir>   # T5 (4-bit) -> ltx_embeds.pt
  python -m autovideo.story.ltx animate <part_dir>  # transformer (fp8 storage) -> clips
Reads <part_dir>/jobs_ltx.json [{image, out, seconds, prompt, seed}]."""
import gc
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
from diffusers import AutoencoderKLLTXVideo, LTXConditionPipeline, LTXVideoTransformer3DModel
from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
from huggingface_hub import hf_hub_download
from PIL import Image

from autovideo.story.gpu import cool_down

REPO = "Lightricks/LTX-Video-0.9.5"  # configs, tokenizer, T5 and VAE
CKPT = ("Lightricks/LTX-Video", "ltxv-2b-0.9.8-distilled.safetensors")
T5_4BIT = Path(os.getenv("HF_HOME", "")) / "t5-xxl-nf4"
STEPS = 8  # distilled model; the pipeline builds the sigma schedule itself
W, H, FPS = 576, 1024, 24
# Short clips that start AND end on the drawn shot: the model can only move things in between and must come
# back to the same face, which stops the identity drift of long clips; the render step loops them seamlessly.
LOOP_FRAMES = 65  # 2.7 s at 24 fps


def jobs(part_dir: Path) -> list[dict]:
    return [j for j in json.loads((part_dir / "jobs_ltx.json").read_text()) if not Path(j["out"]).exists()]


def encode(part_dir: Path):
    from transformers import AutoTokenizer, BitsAndBytesConfig, T5EncoderModel
    todo = jobs(part_dir)
    if not todo:
        return
    if T5_4BIT.exists():
        t5 = T5EncoderModel.from_pretrained(T5_4BIT, device_map="cuda")
    else:  # first run: quantise once (reads the fp32 shards one by one) and keep the 4-bit copy
        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
        t5 = T5EncoderModel.from_pretrained(REPO, subfolder="text_encoder", quantization_config=q,
                                            device_map="cuda", torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
        t5.save_pretrained(T5_4BIT)
    tok = AutoTokenizer.from_pretrained(REPO, subfolder="tokenizer")
    out = {}
    with torch.no_grad():
        for j in todo:
            t = tok(j["prompt"], padding="max_length", max_length=128, truncation=True, return_tensors="pt").to("cuda")
            out[j["out"]] = (t5(t.input_ids, attention_mask=t.attention_mask)[0].to(torch.bfloat16).cpu(),
                             t.attention_mask.cpu())
    torch.save(out, part_dir / "ltx_embeds.pt")


def write_mp4(frames: list, out: Path) -> None:
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                           "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    for f in frames:
        ff.stdin.write(np.asarray(f.convert("RGB")).tobytes())
    ff.stdin.close()
    if ff.wait():
        raise RuntimeError(f"ffmpeg failed on {out}")


def animate(part_dir: Path):
    todo = jobs(part_dir)
    if not todo:
        return
    embeds = torch.load(part_dir / "ltx_embeds.pt")
    ckpt = hf_hub_download(*CKPT)
    transformer = LTXVideoTransformer3DModel.from_single_file(ckpt, config=REPO, subfolder="transformer",
                                                              torch_dtype=torch.bfloat16)
    transformer.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=torch.bfloat16)
    transformer.to("cuda")
    gc.collect()
    vae = AutoencoderKLLTXVideo.from_single_file(ckpt, config=REPO, subfolder="vae", torch_dtype=torch.bfloat16)
    pipe = LTXConditionPipeline.from_pretrained(REPO, transformer=transformer, vae=vae, text_encoder=None,
                                                torch_dtype=torch.bfloat16)
    pipe.vae.to("cuda")
    pipe.vae.enable_tiling()
    for j in todo:
        cool_down()
        pe, mask = embeds[j["out"]]
        n = min(8 * math.ceil(j["seconds"] * FPS / 8) + 1, LOOP_FRAMES)  # LTX wants 8k+1 frames
        image = Image.open(j["image"]).convert("RGB").resize((W, H), Image.LANCZOS)
        keys = [LTXVideoCondition(image=image, frame_index=0), LTXVideoCondition(image=image, frame_index=n - 1)]
        frames = pipe(conditions=keys, prompt_embeds=pe.cuda(), prompt_attention_mask=mask.cuda(), width=W, height=H,
                      num_frames=n, frame_rate=FPS, num_inference_steps=STEPS, guidance_scale=1.0,
                      decode_timestep=0.05, decode_noise_scale=0.025,
                      generator=torch.Generator("cuda").manual_seed(j["seed"])).frames[0]
        tmp = Path(j["out"]).with_suffix(".tmp.mp4")
        write_mp4(frames, tmp)
        tmp.replace(j["out"])
        print("ltx", j["out"], len(frames), "frames", flush=True)


if __name__ == "__main__":
    {"encode": encode, "animate": animate}[sys.argv[1]](Path(sys.argv[2]))
