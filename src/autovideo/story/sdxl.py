"""Draw every shot with SDXL-Lightning (8 steps) on a 6 GB GPU inside ~7 GB of WSL RAM.

Run as its own process (python -m autovideo.story.sdxl <part_dir>) so memory is fully freed after.
Reads <part_dir>/jobs_sdxl.json {model: {...}, jobs: [{out, prompt, seed, candidates}]}, skips existing images.
model.lightning=true: SDXL-Lightning 8-step UNet, no CFG. Otherwise the repo's own UNet with CFG + negative prompt
(e.g. Animagine XL 4.0, which draws far better anatomy than base SDXL).
Weights go straight from disk to the GPU; nothing big is ever copied into RAM (that got us OOM-killed)."""
import gc
import json
import sys
from pathlib import Path

import torch
from accelerate import init_empty_weights
from diffusers import (AutoencoderKL, EulerAncestralDiscreteScheduler, EulerDiscreteScheduler,
                       StableDiffusionXLPipeline, UNet2DConditionModel)
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file
from autovideo.story.gpu import cool_down
from autovideo.story.pick import readable
from transformers import CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer

BASE = "stabilityai/stable-diffusion-xl-base-1.0"
F16 = torch.float16


def fit(tok: CLIPTokenizer, pieces: list[str] | str, limit: int = 75) -> str:
    """Join prompt pieces (most important first), dropping whole pieces that would overflow CLIP."""
    if isinstance(pieces, str):
        return pieces
    kept = []
    for p in pieces:
        if len(tok(", ".join([*kept, p])).input_ids) - 2 <= limit:
            kept.append(p)
    return ", ".join(kept)


def embed(prompts: list[str], repo: str = BASE) -> list[tuple]:
    """SDXL prompt embeddings: penultimate layers of both CLIP encoders, plus the pooled vector."""
    variant = {"variant": "fp16"} if repo == BASE else {}
    encoders = [(CLIPTokenizer.from_pretrained(repo, subfolder=f"tokenizer{s}"),
                 cls.from_pretrained(repo, subfolder=f"text_encoder{s}", torch_dtype=F16, device_map="cuda", **variant))
                for s, cls in (("", CLIPTextModel), ("_2", CLIPTextModelWithProjection))]
    out = []
    with torch.no_grad():
        for p in prompts:
            hidden, pooled = [], None
            for tok, enc in encoders:
                ids = tok(p, padding="max_length", max_length=77, truncation=True, return_tensors="pt").input_ids
                r = enc(ids.to("cuda"), output_hidden_states=True)
                hidden.append(r.hidden_states[-2])
                pooled = r[0]  # text_embeds of the second encoder
            out.append((torch.cat(hidden, -1).cpu(), pooled.cpu()))
    del encoders
    gc.collect()
    torch.cuda.empty_cache()
    return out


def load_unet(model: dict) -> UNet2DConditionModel:
    repo = model["repo"]
    with init_empty_weights():
        unet = UNet2DConditionModel.from_config(UNet2DConditionModel.load_config(repo, subfolder="unet"))
    path = (hf_hub_download("ByteDance/SDXL-Lightning", "sdxl_lightning_8step_unet.safetensors") if model["lightning"]
            else hf_hub_download(repo, "unet/diffusion_pytorch_model.safetensors"))
    weights = {k: v.to(F16) for k, v in load_file(path, device="cuda").items()}
    unet.load_state_dict(weights, assign=True)
    del weights
    # Stored as fp8, computed in fp16: ~2.6 GB instead of 5.1 GB of VRAM.
    unet.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=F16)
    torch.cuda.empty_cache()
    return unet.eval()


def main(part_dir: Path, width: int = 768, height: int = 1344):
    spec = json.loads((part_dir / "jobs_sdxl.json").read_text())
    model = {"repo": BASE, "lightning": True, "steps": 8, "cfg": 0, "negative": "", **spec.get("model", {})}
    jobs = [j for j in spec["jobs"] if not Path(j["out"]).exists() and not all(
        readable(Path(j["out"]).with_suffix(f".c{k}.png")) for k in range(j.get("candidates", 1)))]
    if not jobs:
        return
    repo = model["repo"]
    tok = CLIPTokenizer.from_pretrained(repo, subfolder="tokenizer")
    prompts = [fit(tok, j["prompt"]) for j in jobs]
    for j, p in zip(jobs, prompts):
        print("prompt", Path(j["out"]).name, p, flush=True)
    cfg = model["cfg"] if not model["lightning"] else 0
    embeds = embed(prompts + ([model["negative"]] if cfg else []), repo)
    neg = embeds.pop() if cfg else None
    vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=F16).to("cuda")
    vae.enable_tiling()
    if model["lightning"]:
        sched = EulerDiscreteScheduler.from_pretrained(repo, subfolder="scheduler", timestep_spacing="trailing")
    else:
        sched = EulerAncestralDiscreteScheduler.from_pretrained(repo, subfolder="scheduler")
    pipe = StableDiffusionXLPipeline(vae=vae, text_encoder=None, text_encoder_2=None, tokenizer=None,
                                     tokenizer_2=None, unet=load_unet(model), scheduler=sched)
    if model.get("attention_slicing"):  # only if CFG's doubled batch runs out of VRAM; it is ~10x slower
        pipe.enable_attention_slicing()
    extra = {"negative_prompt_embeds": neg[0].to("cuda", F16),
             "negative_pooled_prompt_embeds": neg[1].to("cuda", F16)} if cfg else {}
    for j, (pe, pooled) in zip(jobs, embeds):
        out = Path(j["out"])
        # Several takes per shot (shot_01.c0.png, .c1, ...); the pick step chooses one as shot_01.png.
        for k in range(j.get("candidates", 1)):
            take = out.with_suffix(f".c{k}.png")
            if not readable(take):
                cool_down()
                img = pipe(prompt_embeds=pe.to("cuda", F16), pooled_prompt_embeds=pooled.to("cuda", F16),
                           num_inference_steps=model["steps"], guidance_scale=cfg, width=width, height=height, **extra,
                           generator=torch.Generator("cuda").manual_seed(j["seed"] + k)).images[0]
                img.save(take.with_suffix(".tmp.png"))
                take.with_suffix(".tmp.png").replace(take)
        print("drew", out, flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
