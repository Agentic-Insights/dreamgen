"""Qwen-Image text-to-image backend with typography-oriented defaults."""

from __future__ import annotations

import gc
import logging
import math
import os
import re
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

import torch
from diffusers import DiffusionPipeline

from ..utils.config import Config
from .factory import (
    incomplete_model_downloads,
    is_model_cached,
    model_cache_path,
    required_model_cache_gb,
)

logger = logging.getLogger(__name__)


class QwenImageGenerator:
    """Diffusers wrapper for Qwen-Image.

    Qwen-Image is especially useful for prompts that need visible text, signage,
    posters, or bilingual English/Chinese typography.
    """

    def __init__(self, config: Config):
        self.config = config
        self.model_name = config.model.qwen_image_model
        self.backend_name = "qwen"
        self.pipe: Optional[DiffusionPipeline] = None
        self.device = self._determine_device(config.system.cpu_only)
        self.height = config.image.height
        self.width = config.image.width
        self.prompt_magic = config.model.qwen_prompt_magic
        self.use_lightning = config.model.qwen_lightning
        self.lightning_lora = config.model.qwen_lightning_lora
        self.lightning_weight = config.model.qwen_lightning_weight
        self.device_map = config.model.qwen_device_map
        self.last_generation_metadata: dict = {}

        self.num_inference_steps = (
            max(config.image.num_inference_steps, 8)
            if self.use_lightning
            else config.image.num_inference_steps
        )
        self.true_cfg_scale = (
            config.image.true_cfg_scale if config.image.true_cfg_scale > 1 else 4.0
        )

        if self.device == "cuda":
            logger.info("Using NVIDIA GPU for Qwen-Image: %s", torch.cuda.get_device_name())
            torch.cuda.set_device(0)
        elif self.device == "mps":
            logger.info("Using Apple Silicon GPU for Qwen-Image")
        else:
            logger.warning("Using CPU for Qwen-Image. Generation will be very slow.")

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

    def _device_map(self) -> str | None:
        if self.device != "cuda":
            return None

        normalized = self.device_map.strip().lower()
        if normalized in {"", "none", "false", "off"}:
            return None
        return normalized

    def _hf_token(self) -> str | None:
        hf_token = os.environ.get("HF_TOKEN")
        return hf_token if hf_token and hf_token != "your_hugging_face_token_here" else None

    def _is_nf4_model(self) -> bool:
        return "qwen-image-nf4" in self.model_name.lower()

    def _load_nf4_balanced_pipeline(self):
        from diffusers import QwenImagePipeline, QwenImageTransformer2DModel
        from transformers import Qwen2_5_VLForConditionalGeneration

        common_kwargs = {
            "cache_dir": self._cache_dir(),
            "token": self._hf_token(),
        }

        transformer = QwenImageTransformer2DModel.from_pretrained(
            self.model_name,
            subfolder="transformer",
            torch_dtype=self._torch_dtype(),
            **common_kwargs,
        )
        transformer.to(self.device)
        text_encoder = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_name,
            subfolder="text_encoder",
            torch_dtype=self._torch_dtype(),
            device_map="cpu",
            **common_kwargs,
        )
        pipe = QwenImagePipeline.from_pretrained(
            self.model_name,
            transformer=transformer,
            text_encoder=text_encoder,
            torch_dtype=self._torch_dtype(),
            **common_kwargs,
        )
        pipe.vae.to(self.device)
        return pipe

    def _cache_dir(self) -> str | None:
        if os.getenv("HF_HOME"):
            return os.path.join(os.getenv("HF_HOME"), "hub")
        if os.getenv("TRANSFORMERS_CACHE"):
            return os.path.join(os.getenv("TRANSFORMERS_CACHE"), "hub")
        return None

    def _validate_cache_ready(self) -> None:
        incomplete = incomplete_model_downloads(self.model_name)
        cache_path = model_cache_path(self.model_name)
        cache_root = cache_path.parent
        cache_root.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(cache_root).free / 1024**3

        if incomplete:
            raise RuntimeError(
                f"Qwen-Image cache has {len(incomplete)} incomplete download(s) under {cache_path}. "
                "Finish the Hugging Face download or delete the incomplete cache files before generation."
            )

        required_gb = required_model_cache_gb(self.model_name)
        if not is_model_cached(self.model_name) and free_gb < required_gb:
            raise RuntimeError(
                f"Qwen-Image is not fully cached and only {free_gb:.1f} GB is free on the "
                f"Hugging Face cache filesystem. Free at least {required_gb} GB or set "
                "HF_HOME/HF_HUB_CACHE to a larger disk before generation."
            )

    def _scheduler(self):
        if not self.use_lightning:
            return None

        from diffusers import FlowMatchEulerDiscreteScheduler

        scheduler_config = {
            "base_image_seq_len": 256,
            "base_shift": math.log(3),
            "invert_sigmas": False,
            "max_image_seq_len": 8192,
            "max_shift": math.log(3),
            "num_train_timesteps": 1000,
            "shift": 1.0,
            "shift_terminal": None,
            "stochastic_sampling": False,
            "time_shift_type": "exponential",
            "use_beta_sigmas": False,
            "use_dynamic_shifting": True,
            "use_exponential_sigmas": False,
            "use_karras_sigmas": False,
        }
        return FlowMatchEulerDiscreteScheduler.from_config(scheduler_config)

    def initialize(self, force_reinit: bool = False) -> None:
        if force_reinit and self.pipe is not None:
            self.cleanup()

        if self.pipe is not None:
            return

        load_kwargs = {
            "dtype": self._torch_dtype(),
            "cache_dir": self._cache_dir(),
            "token": self._hf_token(),
        }
        device_map = self._device_map()
        if device_map is not None:
            load_kwargs["device_map"] = device_map

        scheduler = self._scheduler()
        if scheduler is not None:
            load_kwargs["scheduler"] = scheduler

        self._validate_cache_ready()

        logger.info("Loading Qwen-Image model: %s", self.model_name)
        if self._is_nf4_model() and device_map == "balanced":
            self.pipe = self._load_nf4_balanced_pipeline()
        else:
            self.pipe = DiffusionPipeline.from_pretrained(self.model_name, **load_kwargs)

        if device_map is None:
            self.pipe.to(self.device)
        else:
            logger.info("Loaded Qwen-Image with device_map=%s", device_map)

        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()
        if hasattr(self.pipe, "enable_vae_slicing"):
            self.pipe.enable_vae_slicing()
        if hasattr(self.pipe, "enable_vae_tiling"):
            self.pipe.enable_vae_tiling()

        if self.use_lightning:
            logger.info("Loading Qwen-Image Lightning LoRA: %s", self.lightning_lora)
            self.pipe.load_lora_weights(self.lightning_lora, weight_name=self.lightning_weight)

    def _looks_chinese(self, prompt: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", prompt))

    def _effective_prompt(self, prompt: str) -> str:
        if not self.prompt_magic:
            return prompt

        magic = "Ultra HD, 4K, cinematic composition"
        if self._looks_chinese(prompt):
            magic = "超清，4K，电影级构图"

        normalized = prompt.lower()
        if magic.lower() in normalized or "ultra hd" in normalized:
            return prompt

        separator = "" if prompt.rstrip().endswith((".", ",", ";")) else ","
        return f"{prompt.rstrip()}{separator} {magic}."

    def _balanced_prompt_embeddings(self, prompt: str, negative_prompt: str | None) -> dict:
        target_dtype = self.pipe.transformer.dtype
        prompt_embeds, prompt_embeds_mask = self.pipe.encode_prompt(
            prompt=prompt,
            device=torch.device("cpu"),
            max_sequence_length=self.config.model.max_sequence_length,
        )
        prompt_kwargs = {
            "prompt": None,
            "negative_prompt": None,
            "prompt_embeds": prompt_embeds.to(device=self.device, dtype=target_dtype),
            "prompt_embeds_mask": prompt_embeds_mask.to(self.device),
        }

        if negative_prompt is not None:
            negative_prompt_embeds, negative_prompt_embeds_mask = self.pipe.encode_prompt(
                prompt=negative_prompt,
                device=torch.device("cpu"),
                max_sequence_length=self.config.model.max_sequence_length,
            )
            prompt_kwargs["negative_prompt_embeds"] = negative_prompt_embeds.to(
                device=self.device, dtype=target_dtype
            )
            prompt_kwargs["negative_prompt_embeds_mask"] = negative_prompt_embeds_mask.to(
                self.device
            )

        return prompt_kwargs

    async def generate(self, prompt: str, seed: Optional[int] = None):
        from ..utils.storage import StorageManager

        storage = StorageManager()
        output_path = storage.get_output_path(prompt)
        await self.generate_image(prompt, output_path, seed=seed)

        from PIL import Image

        return Image.open(output_path)

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        force_reinit: bool = False,
        seed: Optional[int] = None,
    ) -> tuple[Path, float, str]:
        start = time.time()
        self.initialize(force_reinit)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        resolved_seed = seed if seed is not None else torch.randint(0, 2**32, (1,)).item()
        generator_device = (
            self.device if self.device != "mps" and self._device_map() != "balanced" else "cpu"
        )
        generator = torch.Generator(device=generator_device).manual_seed(resolved_seed)
        effective_prompt = self._effective_prompt(prompt)
        negative_prompt = " "
        prompt_kwargs = (
            self._balanced_prompt_embeddings(
                effective_prompt,
                negative_prompt if self.true_cfg_scale > 1 else None,
            )
            if self._is_nf4_model() and self._device_map() == "balanced"
            else {"prompt": effective_prompt, "negative_prompt": negative_prompt}
        )

        balanced_nf4 = self._is_nf4_model() and self._device_map() == "balanced"
        text_encoder = self.pipe.text_encoder if balanced_nf4 else None
        if balanced_nf4:
            self.pipe.text_encoder = None

        try:
            with torch.inference_mode():
                image = self.pipe(
                    **prompt_kwargs,
                    width=self.width,
                    height=self.height,
                    num_inference_steps=self.num_inference_steps,
                    true_cfg_scale=self.true_cfg_scale,
                    generator=generator,
                    max_sequence_length=self.config.model.max_sequence_length,
                ).images[0]
        finally:
            if balanced_nf4:
                self.pipe.text_encoder = text_encoder

        image.save(output_path)
        with open(output_path.with_suffix(".txt"), "w", encoding="utf-8") as f:
            f.write(effective_prompt)

        self.last_generation_metadata = {
            "model": self.model_name,
            "device": self.device,
            "height": self.height,
            "width": self.width,
            "steps": self.num_inference_steps,
            "true_cfg_scale": self.true_cfg_scale,
            "seed": resolved_seed,
            "device_map": self._device_map(),
            "prompt_magic": self.prompt_magic,
            "effective_prompt": effective_prompt,
            "lightning_lora": self.lightning_lora if self.use_lightning else None,
            "lightning_weight": self.lightning_weight if self.use_lightning else None,
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
                "High-fidelity text rendering",
                "English and Chinese typography",
                "Poster and signage prompts",
                "Optional Lightning LoRA few-step mode",
            ],
        }
