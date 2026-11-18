"""Fetch every model the story pipeline needs into story.models_dir (resumable; rerun anytime)."""
from huggingface_hub import hf_hub_download, snapshot_download

hf_hub_download("ByteDance/SDXL-Lightning", "sdxl_lightning_8step_unet.safetensors")
snapshot_download("stabilityai/stable-diffusion-xl-base-1.0", allow_patterns=[
    "model_index.json", "*/config.json", "scheduler/*", "tokenizer*/*",
    "text_encoder/model.fp16.safetensors", "text_encoder_2/model.fp16.safetensors"])
snapshot_download("madebyollin/sdxl-vae-fp16-fix", allow_patterns=["config.json", "diffusion_pytorch_model.safetensors"])
snapshot_download("depth-anything/Depth-Anything-V2-Small-hf")
hf_hub_download("Lightricks/LTX-Video", "ltxv-2b-0.9.8-distilled.safetensors")
snapshot_download("Lightricks/LTX-Video-0.9.5", allow_patterns=[
    "model_index.json", "*/config.json", "scheduler/*", "tokenizer/*", "text_encoder/*", "vae/*", "*.txt"])
snapshot_download("cagliostrolab/animagine-xl-4.0", allow_patterns=[
    "model_index.json", "*/config.json", "scheduler/*", "tokenizer*/*", "text_encoder*/model.safetensors",
    "unet/diffusion_pytorch_model.safetensors"])
snapshot_download("openai/clip-vit-large-patch14", allow_patterns=["*.json", "*.txt", "model.safetensors"])
print("ALL MODELS READY", flush=True)
