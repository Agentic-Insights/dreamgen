"""Tests for the Qwen-Image backend wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image

from src.generators import qwen_image_generator

QwenImageGenerator = qwen_image_generator.QwenImageGenerator


def make_config(tmp_path: Path):
    config = MagicMock()
    config.model.qwen_image_model = "diffusers/qwen-image-nf4"
    config.model.qwen_prompt_magic = True
    config.model.qwen_device_map = "cuda"
    config.model.qwen_lightning = False
    config.model.qwen_lightning_lora = "lightx2v/Qwen-Image-Lightning"
    config.model.qwen_lightning_weight = "Qwen-Image-Lightning-8steps-V1.0.safetensors"
    config.model.max_sequence_length = 512
    config.image.height = 512
    config.image.width = 512
    config.image.num_inference_steps = 4
    config.image.true_cfg_scale = 1.0
    config.system.cpu_only = True
    config.system.mps_use_fp16 = False
    config.system.output_dir = tmp_path
    return config


def test_prompt_magic_adds_english_typography_suffix(tmp_path):
    generator = QwenImageGenerator(make_config(tmp_path))

    prompt = generator._effective_prompt('A diner window sign reading "OPEN LATE"')

    assert prompt.endswith("Ultra HD, 4K, cinematic composition.")


def test_prompt_magic_uses_chinese_suffix_for_chinese_text(tmp_path):
    generator = QwenImageGenerator(make_config(tmp_path))

    prompt = generator._effective_prompt('A neon sign reading "通义千问"')

    assert prompt.endswith("超清，4K，电影级构图.")


async def test_generate_image_uses_diffusers_pipeline(monkeypatch, tmp_path):
    config = make_config(tmp_path)
    config.system.cpu_only = False
    monkeypatch.setattr(qwen_image_generator.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        qwen_image_generator.torch.cuda,
        "get_device_name",
        lambda: "Test CUDA GPU",
    )
    monkeypatch.setattr(qwen_image_generator.torch.cuda, "set_device", lambda _id: None)
    generator = QwenImageGenerator(config)
    output_path = tmp_path / "qwen.png"
    image = Image.new("RGB", (32, 32), "white")

    pipe = MagicMock()
    pipe.return_value.images = [image]
    pipe.to.return_value = pipe

    pipeline_cls = MagicMock()
    pipeline_cls.from_pretrained.return_value = pipe
    monkeypatch.setattr(qwen_image_generator, "DiffusionPipeline", pipeline_cls)
    monkeypatch.setattr(qwen_image_generator, "incomplete_model_downloads", lambda _model: [])
    monkeypatch.setattr(qwen_image_generator, "is_model_cached", lambda _model: True)

    path, _duration, model_name = await generator.generate_image(
        'A poster that says "DREAMGEN"',
        output_path,
        seed=123,
    )

    assert path == output_path
    assert output_path.exists()
    assert model_name == "qwen-image-nf4"
    assert generator.last_generation_metadata["seed"] == 123
    assert generator.last_generation_metadata["steps"] == 4
    pipe.assert_called_once()
    assert "device_map" not in pipeline_cls.from_pretrained.call_args.kwargs
    pipe.to.assert_called_once_with("cuda")
    assert pipe.call_args.kwargs["true_cfg_scale"] == 4.0
