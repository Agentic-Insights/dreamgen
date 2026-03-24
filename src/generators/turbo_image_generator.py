"""Turbo text-to-image backend for fast real image generation."""

from __future__ import annotations

import gc
import logging
import os
import platform
import time
from pathlib import Path
from typing import Literal, Optional, Tuple

import torch
from diffusers import AutoPipelineForText2Image
from PIL import Image

from ..utils.config import Config

logger = logging.getLogger(__name__)


class TurboImageGenerator:
    """Fast few-step text-to-image backend for sd-turbo / sdxl-turbo style models."""

    def __init__(self, config: Config):
        self.config = config
        self.model_name = config.model.turbo_model
        self.pipe = None
        self.device = self._determine_device(config.system.cpu_only)

        self.height = min(config.image.height, 512)
        self.width = min(config.image.width, 512)
        self.num_inference_steps = min(max(config.image.num_inference_steps, 1), 4)
        self.guidance_scale = 0.0

        if self.device == "cuda":
            logger.info("Using NVIDIA GPU for turbo backend: %s", torch.cuda.get_device_name())
            torch.cuda.set_device(0)
        elif self.device == "mps":
            logger.info("Using Apple Silicon GPU for turbo backend: %s", platform.processor())
        else:
            logger.info("Using CPU for turbo backend")

    def _determine_device(self, cpu_only: bool) -> Literal["cpu", "cuda", "mps"]:
        if cpu_only:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def initialize(self, force_reinit: bool = False) -> None:
        if force_reinit and self.pipe is not None:
            self.cleanup()

        if self.pipe is not None:
            return

        hf_token = os.environ.get("HF_TOKEN")
        cache_dir = None
        if os.getenv("HF_HOME"):
            cache_dir = os.path.join(os.getenv("HF_HOME"), "hub")
        elif os.getenv("TRANSFORMERS_CACHE"):
            cache_dir = os.path.join(os.getenv("TRANSFORMERS_CACHE"), "hub")

        torch_dtype = torch.float16 if self.device == "cuda" else torch.float32

        self.pipe = AutoPipelineForText2Image.from_pretrained(
            self.model_name,
            torch_dtype=torch_dtype,
            cache_dir=cache_dir,
            token=hf_token if hf_token and hf_token != "your_hugging_face_token_here" else None,
        )

        if self.device == "cuda":
            self.pipe.to(self.device)
            self.pipe.enable_attention_slicing()
            if hasattr(self.pipe, "enable_vae_slicing"):
                self.pipe.enable_vae_slicing()
        elif self.device == "mps":
            self.pipe.to(self.device)
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

        generator = None
        if seed is not None:
            generator = torch.Generator(device=self.device if self.device != "mps" else "cpu")
            generator.manual_seed(seed)

        with torch.inference_mode():
            image = self.pipe(
                prompt=prompt,
                num_inference_steps=self.num_inference_steps,
                guidance_scale=self.guidance_scale,
                height=self.height,
                width=self.width,
                generator=generator,
            ).images[0]

        image.save(output_path)
        with open(output_path.with_suffix(".txt"), "w", encoding="utf-8") as f:
            f.write(prompt)

        return output_path, time.time() - start, self.model_name.split("/")[-1]

    def cleanup(self) -> None:
        self.pipe = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
