"""LoRA prompt-role metadata and conditioning tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.generators.prompt_generator import PromptGenerator
from src.plugins.lora import SelectedLora, condition_prompt_for_lora, get_lora_metadata
from src.utils.generation_plan import GenerationPlan
from src.utils.ollama import OllamaModelInfo
from src.utils.plugin_manager import PluginResult


def test_installed_lora_metadata_distinguishes_prompt_role():
    pixel = get_lora_metadata("pxlstl")
    assert pixel.kind == "style"
    assert pixel.trigger == "pxlstl"
    assert pixel.trigger_placement == "suffix"
    assert pixel.trigger_required is True
    assert pixel.base_model == "Tongyi-MAI/Z-Image-Turbo"
    assert pixel.source == "https://huggingface.co/mks0813/z-image-turbo-pixel-art-lora"

    drawings = get_lora_metadata("childrens drawings")
    assert drawings.kind == "style"
    assert drawings.trigger_required is False


def test_style_and_object_loras_condition_prompts_differently(tmp_path):
    weights = tmp_path / "adapter.safetensors"
    style = SelectedLora("pixel", weights, "pxlstl", "style", "suffix", True)
    object_lora = SelectedLora("robot", weights, "rb0tkn", "object", "subject", True)
    no_trigger = SelectedLora("drawings", weights, "childrens drawings", "style", "suffix", False)

    assert condition_prompt_for_lora("A fox beneath amber trees", style) == (
        "A fox beneath amber trees, pxlstl"
    )
    assert condition_prompt_for_lora("A fox beneath amber trees.", style) == (
        "A fox beneath amber trees, pxlstl"
    )
    assert condition_prompt_for_lora("A fox beneath amber trees, 'pxlstl'", style) == (
        "A fox beneath amber trees, pxlstl"
    )
    repaired = condition_prompt_for_lora("A studio where 'pxlstl' paints stars", style)
    assert repaired.endswith(", pxlstl")
    assert repaired.lower().count("pxlstl") == 1
    assert "'pxlstl'" not in repaired

    assert condition_prompt_for_lora("A brass robot in a workshop", object_lora) == (
        "rb0tkn, A brass robot in a workshop"
    )
    assert condition_prompt_for_lora("Portrait of 'rb0tkn' in a workshop", object_lora) == (
        "Portrait of rb0tkn in a workshop"
    )
    assert condition_prompt_for_lora("Crayon animals on white paper", no_trigger) == (
        "Crayon animals on white paper"
    )


@pytest.mark.asyncio
async def test_style_trigger_is_hidden_from_ollama_and_appended_as_suffix(monkeypatch, tmp_path):
    config = MagicMock()
    config.model.ollama_model = "ornith:9b"
    config.model.ollama_temperature = 0.7
    weights = tmp_path / "pxlstl.safetensors"
    selection = SelectedLora("pxlstl", weights, "pxlstl", "style", "suffix", True)
    plan = GenerationPlan(
        plugin_results=(
            PluginResult("time_of_day", "afternoon", "time context"),
            PluginResult("lora", "pxlstl", "pixel adapter"),
        ),
        plugin_descriptions=("time_of_day: time context", "lora: pixel adapter"),
        enabled_plugins=("time_of_day", "lora"),
        temporal_descriptor="afternoon",
        selected_lora=selection,
    )
    captured_messages = []
    fake_ollama = ModuleType("ollama")

    def fake_chat(*, model, messages, options, keep_alive):
        del model, options, keep_alive
        captured_messages.extend(messages)
        return SimpleNamespace(
            message=SimpleNamespace(
                content="Afternoon, a red fox watches fireflies above an amber forest"
            )
        )

    fake_ollama.chat = fake_chat
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)
    monkeypatch.setattr(
        "src.generators.prompt_generator.list_ollama_models",
        lambda: [
            OllamaModelInfo(
                name="ornith:9b",
                size=1,
                modified="2026-07-16T00:00:00Z",
                digest="digest",
                format="gguf",
                family="qwen",
                capabilities=["completion"],
                can_prompt=True,
                can_vision=False,
                can_image=False,
            )
        ],
    )

    prompt = await PromptGenerator(config, plan).generate_prompt()

    messages_seen_by_ollama = "\n".join(message["content"] for message in captured_messages)
    assert "pxlstl" not in messages_seen_by_ollama
    assert "central subject" not in messages_seen_by_ollama
    assert prompt == ("Afternoon, a red fox watches fireflies above an amber forest, pxlstl")
    assert "'pxlstl'" not in prompt
