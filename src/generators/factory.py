"""Shared image backend selection for API and CLI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from ..utils.config import Config
from .mock_image_generator import MockImageGenerator
from .stable_diffusion_image_generator import StableDiffusionImageGenerator


def _hf_cache_root() -> Path:
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"

    transformers_cache = os.getenv("TRANSFORMERS_CACHE")
    if transformers_cache:
        return Path(transformers_cache) / "hub"

    return Path(os.getenv("HF_HUB_CACHE", os.path.expanduser("~/.cache/huggingface/hub")))


def model_cache_path(model_id: str) -> Path:
    """Return the Hugging Face cache path for a model repository."""
    return _hf_cache_root() / f"models--{model_id.replace('/', '--')}"


def incomplete_model_downloads(model_id: str) -> list[Path]:
    """Return incomplete blob downloads for a cached model repository."""
    blobs_path = model_cache_path(model_id) / "blobs"
    if not blobs_path.exists():
        return []
    return list(blobs_path.glob("*.incomplete"))


def is_model_cached(model_id: str) -> bool:
    model_path = model_cache_path(model_id)
    snapshots_path = model_path / "snapshots"
    return (
        model_path.exists()
        and snapshots_path.exists()
        and any(snapshots_path.iterdir())
        and not incomplete_model_downloads(model_id)
    )


def required_model_cache_gb(model_id: str) -> int:
    """Return a conservative free-space guardrail for model downloads."""
    normalized = model_id.lower()
    if normalized == "qwen/qwen-image":
        return 60
    if "qwen-image" in normalized:
        return 30
    if "ernie-image" in normalized:
        return 35
    return 25


def resolve_image_backend(config: Config) -> str:
    backend = config.model.image_backend
    if backend == "tiny":
        backend = "smoke"
    if backend != "auto":
        return backend

    if is_model_cached(config.model.flux_model):
        return "flux"

    if is_model_cached(config.model.small_sd_model):
        return "small"

    return "small"


def backend_label(config: Config, backend: str) -> str:
    if backend == "mock":
        return "mock"
    if backend == "smoke":
        return "smoke-test"
    if backend == "small":
        return "small-sd"
    if backend == "turbo":
        return "sd-turbo"
    if backend == "ollama":
        return "ollama"
    if backend == "zimage":
        return "z-image"
    if backend == "qwen":
        return "qwen-image"
    if backend == "ernie":
        return "ernie-image"

    flux_model = config.model.flux_model.lower()
    if "schnell" in flux_model:
        return "flux-schnell"
    if "dev" in flux_model:
        return "flux-dev"
    return "flux"


def create_image_generator(config: Config) -> Tuple[object, str]:
    backend = resolve_image_backend(config)
    if backend == "mock":
        return MockImageGenerator(config), backend_label(config, backend)
    if backend == "smoke":
        return (
            StableDiffusionImageGenerator(
                config,
                model_name=config.model.smoke_test_model,
                backend_name="smoke",
                max_size=512,
                min_steps=10,
                default_guidance_scale=7.5,
            ),
            backend_label(config, backend),
        )
    if backend == "small":
        return (
            StableDiffusionImageGenerator(
                config,
                model_name=config.model.small_sd_model,
                backend_name="small",
                max_size=512,
                min_steps=25,
                default_guidance_scale=7.5,
            ),
            backend_label(config, backend),
        )
    if backend == "turbo":
        from .turbo_image_generator import TurboImageGenerator

        return TurboImageGenerator(config), backend_label(config, backend)
    if backend == "ollama":
        from .ollama_image_generator import OllamaImageGenerator

        return OllamaImageGenerator(config), backend_label(config, backend)
    if backend == "zimage":
        from .zimage_generator import ZImageGenerator

        return ZImageGenerator(config), backend_label(config, backend)
    if backend == "qwen":
        from .qwen_image_generator import QwenImageGenerator

        return QwenImageGenerator(config), backend_label(config, backend)
    if backend == "ernie":
        from .ernie_image_generator import ErnieImageGenerator

        return ErnieImageGenerator(config), backend_label(config, backend)
    if backend == "flux":
        from .image_generator import ImageGenerator

        return ImageGenerator(config), backend_label(config, backend)
    raise ValueError(f"Unsupported image backend: {backend}")
