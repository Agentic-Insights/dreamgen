"""Targeted tests for Ollama-backed prompt and image generation."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.generators.ollama_image_generator import OllamaImageGenerator
from src.generators.prompt_generator import PromptGenerator
from src.utils.ollama import OllamaModelInfo


def _completion_model(name: str) -> OllamaModelInfo:
    return OllamaModelInfo(
        name=name,
        size=1,
        modified="2026-04-24T00:00:00Z",
        digest="digest",
        format="gguf",
        family="qwen",
        capabilities=["completion"],
        can_prompt=True,
        can_vision=False,
        can_image=False,
    )


def _image_model(name: str) -> OllamaModelInfo:
    return OllamaModelInfo(
        name=name,
        size=1,
        modified="2026-04-24T00:00:00Z",
        digest="digest",
        format="safetensors",
        family="ZImagePipeline",
        capabilities=["image"],
        can_prompt=False,
        can_vision=False,
        can_image=True,
    )


@pytest.mark.asyncio
async def test_prompt_generator_falls_back_to_available_completion_model(monkeypatch):
    """Prompt generation should recover when the configured model is unavailable."""
    config = MagicMock()
    config.model.ollama_model = "llama3.2:3b"
    config.model.ollama_temperature = 0.7

    chat_calls: list[str] = []

    fake_ollama = ModuleType("ollama")

    def fake_chat(*, model, messages, options):
        del messages, options
        chat_calls.append(model)
        return SimpleNamespace(message=SimpleNamespace(content="sunlit alley, cinematic framing"))

    fake_ollama.chat = fake_chat
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)
    monkeypatch.setattr(
        "src.generators.prompt_generator.list_ollama_models",
        lambda: [_image_model("x/z-image-turbo:latest"), _completion_model("qwen3.6:27b")],
    )
    monkeypatch.setattr(
        "src.generators.prompt_generator.get_context_with_descriptions",
        lambda: {"results": [], "descriptions": []},
    )
    monkeypatch.setattr(
        "src.generators.prompt_generator.get_temporal_descriptor",
        lambda: "afternoon",
    )

    generator = PromptGenerator(config)
    prompt = await generator.generate_prompt()

    assert prompt == "sunlit alley, cinematic framing"
    assert chat_calls == ["qwen3.6:27b"]
    assert generator.model_name == "qwen3.6:27b"


@pytest.mark.asyncio
async def test_ollama_image_generator_uses_resolved_image_model(monkeypatch, tmp_path):
    """The Ollama image backend should resolve an image-capable model and save the image."""
    config = MagicMock()
    config.model.ollama_image_model = "x/z-image-turbo"
    config.image.width = 512
    config.image.height = 512

    monkeypatch.setattr(
        "src.generators.ollama_image_generator.list_ollama_models",
        lambda: [_image_model("x/z-image-turbo:latest")],
    )
    monkeypatch.setattr(
        "src.generators.ollama_image_generator.generate_image_via_ollama",
        lambda *, model_name, prompt, width, height: Image.new(
            "RGB", (width, height), color=(0, 0, 255)
        ),
    )

    generator = OllamaImageGenerator(config)
    output_path = tmp_path / "ollama.png"
    saved_path, _, model_name = await generator.generate_image(
        "A bright blue square",
        output_path,
        seed=123,
    )

    assert saved_path == output_path
    assert saved_path.exists()
    assert model_name == "x/z-image-turbo:latest"
    assert generator.last_generation_metadata["provider"] == "ollama"
    assert generator.last_generation_metadata["ollama_model"] == "x/z-image-turbo:latest"
    assert generator.last_generation_metadata["seed_supported"] is False
    assert saved_path.with_suffix(".txt").read_text(encoding="utf-8") == "A bright blue square"
