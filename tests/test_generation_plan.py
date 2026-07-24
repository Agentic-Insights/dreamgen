"""Tests for immutable per-job plugin and LoRA resolution."""

from pathlib import Path
from unittest.mock import MagicMock

from src.plugins import plugin_manager
from src.plugins.lora import SelectedLora
from src.utils.generation_plan import resolve_generation_plan


def test_generation_plan_resolves_lora_once_and_hashes_provenance(monkeypatch, tmp_path):
    original_plugins = dict(plugin_manager.plugins)
    lora_path = tmp_path / "loras" / "locked-style" / "epoch-1.safetensors"
    lora_path.parent.mkdir(parents=True)
    lora_path.write_bytes(b"locked lora weights")

    config = MagicMock()
    config.plugins.enabled_plugins = ["time_of_day", "lora"]
    config.plugins.plugin_order = {"time_of_day": 1, "lora": 5}
    config.model.lora.lora_dir = tmp_path / "loras"
    config.model.lora.enabled_loras = ["locked-style"]
    config.model.lora.application_probability = 1.0

    selection_calls = 0

    def select_once(_config):
        nonlocal selection_calls
        selection_calls += 1
        return SelectedLora("locked-style", lora_path, "locked-trigger")

    def unexpected_lora_plugin_call(_config):
        raise AssertionError("the LoRA plugin was executed after its job-level override")

    try:
        plugin_manager.plugins.clear()
        plugin_manager.register(
            "time_of_day",
            "time context",
            lambda: "night",
            enabled=True,
            order=1,
        )
        monkeypatch.setattr("src.utils.generation_plan.select_random_lora", select_once)
        monkeypatch.setattr("src.plugins.apply_lora", unexpected_lora_plugin_call)

        plan = resolve_generation_plan(config)
        metadata = plan.to_metadata(lora_backend="diffsynth")

        assert selection_calls == 1
        assert [result.value for result in plan.plugin_results] == ["night", "locked-trigger"]
        assert plan.temporal_descriptor == "night"
        assert plan.selected_lora == SelectedLora("locked-style", lora_path, "locked-trigger")
        assert metadata["resolution"] == "once_per_job"
        assert metadata["selected_lora"]["backend"] == "diffsynth"
        assert metadata["selected_lora"]["kind"] == "style"
        assert metadata["selected_lora"]["trigger_placement"] == "suffix"
        assert metadata["selected_lora"]["trigger_required"] is True
        assert metadata["selected_lora"]["display_name"] == "locked-style"
        assert metadata["selected_lora"]["path"] == str(lora_path.resolve())
        assert metadata["selected_lora"]["sha256"]
    finally:
        plugin_manager.plugins.clear()
        plugin_manager.plugins.update(original_plugins)
