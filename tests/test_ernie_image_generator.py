"""Tests for the ERNIE-Image backend wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import torch
from PIL import Image

import src.generators.ernie_image_generator as ernie_module
from src.generators.ernie_image_generator import ErnieImageGenerator
from src.utils.config import Config


def make_config(tmp_path: Path) -> Config:
    config = Config()
    config.model.image_backend = "ernie"
    config.model.ernie_image_model = "baidu/ERNIE-Image-Turbo"
    config.model.ernie_prompt_enhancer = True
    config.system.cpu_only = True
    config.image.height = 1024
    config.image.width = 1024
    config.image.num_inference_steps = 25
    config.image.guidance_scale = 0.0
    config.system.output_dir = tmp_path
    return config


@pytest.mark.asyncio
async def test_generate_image_uses_ernie_pipeline(monkeypatch, tmp_path):
    """ERNIE generation should call the Diffusers pipeline with Turbo defaults."""
    config = make_config(tmp_path)
    generator = ErnieImageGenerator(config)
    output_path = tmp_path / "ernie.png"
    image = Image.new("RGB", (32, 32), "white")

    pipe = MagicMock()
    pipe.return_value.images = [image]
    pipeline_cls = MagicMock()
    pipeline_cls.from_pretrained.return_value = pipe

    monkeypatch.setattr(ernie_module, "ErnieImagePipeline", pipeline_cls)
    monkeypatch.setattr(ernie_module, "incomplete_model_downloads", lambda _model: [])
    monkeypatch.setattr(ernie_module, "is_model_cached", lambda _model: True)

    path, _duration, model_name = await generator.generate_image(
        'A bilingual poster that says "DREAMGEN"',
        output_path,
        seed=123,
    )

    assert path == output_path
    assert path.exists()
    assert model_name == "ERNIE-Image-Turbo"
    pipeline_cls.from_pretrained.assert_called_once()
    _, load_kwargs = pipeline_cls.from_pretrained.call_args
    assert load_kwargs["torch_dtype"] == torch.float32
    _, call_kwargs = pipe.call_args
    assert call_kwargs["width"] == 1024
    assert call_kwargs["height"] == 1024
    assert call_kwargs["num_inference_steps"] == 8
    assert call_kwargs["guidance_scale"] == 1.0
    assert call_kwargs["use_pe"] is True
    assert generator.last_generation_metadata["prompt_enhancer"] is True
