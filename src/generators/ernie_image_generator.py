"""ERNIE-Image text-to-image backend with prompt-enhanced local generation."""

from __future__ import annotations

import gc
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Literal, Optional, Tuple

import torch
from PIL import Image

try:  # Diffusers main exposes this pipeline before older stable releases.
    from diffusers import ErnieImagePipeline
except ImportError:  # pragma: no cover - exercised when runtime dependency is too old.
    ErnieImagePipeline = None  # type: ignore[assignment]

from ..utils.config import Config
from .factory import (
    incomplete_model_downloads,
    is_model_cached,
    model_cache_path,
    required_model_cache_gb,
)

logger = logging.getLogger(__name__)


class ErnieImageGenerator:
    """Diffusers wrapper for Baidu ERNIE-Image and ERNIE-Image-Turbo.

    ERNIE-Image is a recent 8B DiT text-to-image family with an optional prompt
    enhancer. The Turbo checkpoint is the default because it targets 8-step local
    generation while keeping ERNIE's multilingual text-rendering strengths.
    """

    def __init__(self, config: Config):
        self.config = config
        self.model_name = config.model.ernie_image_model
        self.backend_name = "ernie"
        self.pipe: Optional[object] = None
        self.device = self._determine_device(config.system.cpu_only)
        self.height = config.image.height
        self.width = config.image.width
        self.use_prompt_enhancer = config.model.ernie_prompt_enhancer
        self.last_generation_metadata: dict = {}

        is_turbo = self._is_turbo_model()
        self.num_inference_steps = (
            min(max(config.image.num_inference_steps, 1), 8)
            if is_turbo
            else max(config.image.num_inference_steps, 30)
        )
        self.guidance_scale = config.image.guidance_scale
        if self.guidance_scale <= 0:
            self.guidance_scale = 1.0 if is_turbo else 4.0

        if self.device == "cuda":
            logger.info("Using NVIDIA GPU for ERNIE-Image: %s", torch.cuda.get_device_name())
            torch.cuda.set_device(0)
        elif self.device == "mps":
            logger.info("Using Apple Silicon GPU for ERNIE-Image")
        else:
            logger.warning("Using CPU for ERNIE-Image. Generation will be very slow.")

    def _determine_device(self, cpu_only: bool) -> Literal["cpu", "cuda", "mps"]:
        if cpu_only:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _torch_dtype(self):
        if self.device == "cuda":
            return torch.bfloat16
        if self.device == "mps" and self.config.system.mps_use_fp16:
            return torch.float16
        return torch.float32

    def _hf_token(self) -> str | None:
        hf_token = os.environ.get("HF_TOKEN")
        return hf_token if hf_token and hf_token != "your_hugging_face_token_here" else None

    def _cache_dir(self) -> str | None:
        if os.getenv("HF_HOME"):
            return os.path.join(os.getenv("HF_HOME"), "hub")
        if os.getenv("TRANSFORMERS_CACHE"):
            return os.path.join(os.getenv("TRANSFORMERS_CACHE"), "hub")
        return None

    def _is_turbo_model(self) -> bool:
        return "turbo" in self.model_name.lower()

    def _validate_cache_ready(self) -> None:
        incomplete = incomplete_model_downloads(self.model_name)
        cache_path = model_cache_path(self.model_name)
        cache_root = cache_path.parent
        cache_root.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(cache_root).free / 1024**3

        if incomplete:
            raise RuntimeError(
                f"ERNIE-Image cache has {len(incomplete)} incomplete download(s) under "
                f"{cache_path}. Finish the Hugging Face download or delete the incomplete "
                "cache files before generation."
            )

        required_gb = required_model_cache_gb(self.model_name)
        if not is_model_cached(self.model_name) and free_gb < required_gb:
            raise RuntimeError(
                f"ERNIE-Image is not fully cached and only {free_gb:.1f} GB is free on the "
                f"Hugging Face cache filesystem. Free at least {required_gb} GB or set "
                "HF_HOME/HF_HUB_CACHE to a larger disk before generation."
            )

    def initialize(self, force_reinit: bool = False) -> None:
        if force_reinit and self.pipe is not None:
            self.cleanup()

        if self.pipe is not None:
            return

        if ErnieImagePipeline is None:
            raise RuntimeError(
                "ERNIE-Image requires a Diffusers build that includes ErnieImagePipeline. "
                "Run `uv sync` so the configured Hugging Face Diffusers source checkout is installed."
            )

        self._validate_cache_ready()

        logger.info("Loading ERNIE-Image model: %s", self.model_name)
        self.pipe = ErnieImagePipeline.from_pretrained(
            self.model_name,
            torch_dtype=self._torch_dtype(),
            cache_dir=self._cache_dir(),
            token=self._hf_token(),
        )

        if self.device == "cuda":
            if hasattr(self.pipe, "enable_model_cpu_offload"):
                self.pipe.enable_model_cpu_offload()
            else:
                self.pipe.to(self.device)
            if hasattr(self.pipe, "enable_attention_slicing"):
                self.pipe.enable_attention_slicing()
            if hasattr(self.pipe, "enable_vae_slicing"):
                self.pipe.enable_vae_slicing()
            if hasattr(self.pipe, "enable_vae_tiling"):
                self.pipe.enable_vae_tiling()
        elif self.device == "mps":
            self.pipe.to(self.device)
            if hasattr(self.pipe, "enable_attention_slicing"):
                self.pipe.enable_attention_slicing()

    async def generate(self, prompt: str, seed: Optional[int] = None) -> Image.Image:
        from ..utils.storage import StorageManager

        storage = StorageManager()
        output_path = storage.get_output_path(prompt)
        await self.generate_image(prompt, output_path, force_reinit=False, seed=seed)
        return Image.open(output_path)

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        force_reinit: bool = False,
        seed: Optional[int] = None,
    ) -> Tuple[Path, float, str]:
        start = time.time()
        self.initialize(force_reinit)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        resolved_seed = seed if seed is not None else torch.randint(0, 2**32, (1,)).item()
        generator_device = self.device if self.device != "mps" else "cpu"
        generator = torch.Generator(device=generator_device).manual_seed(resolved_seed)

        with torch.inference_mode():
            image = self.pipe(
                prompt=prompt,
                width=self.width,
                height=self.height,
                num_inference_steps=self.num_inference_steps,
                guidance_scale=self.guidance_scale,
                generator=generator,
                use_pe=self.use_prompt_enhancer,
            ).images[0]

        image.save(output_path)
        with open(output_path.with_suffix(".txt"), "w", encoding="utf-8") as f:
            f.write(prompt)

        self.last_generation_metadata = {
            "model": self.model_name,
            "device": self.device,
            "height": self.height,
            "width": self.width,
            "steps": self.num_inference_steps,
            "guidance_scale": self.guidance_scale,
            "seed": resolved_seed,
            "prompt_enhancer": self.use_prompt_enhancer,
        }

        return output_path, time.time() - start, self.model_name.split("/")[-1]

    def cleanup(self) -> None:
        self.pipe = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if torch.cuda.is_initialized():
                torch.cuda.ipc_collect()

    def get_model_info(self) -> dict:
        return {
            "device": self.device,
            "model_type": self.__class__.__name__,
            "model_name": self.model_name,
            "features": [
                "ERNIE-Image 8B DiT architecture",
                "Turbo 8-step local generation",
                "Built-in prompt enhancer toggle",
                "English, Chinese, and Japanese text rendering",
            ],
        }
