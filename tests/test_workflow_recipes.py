"""Tests for workflow recipe loading and resolution."""

from unittest.mock import MagicMock

from src.plugins import plugin_manager
from src.services import (
    apply_config_overrides,
    get_workflow_recipe,
    list_workflow_recipes,
    resolve_workflow_recipe,
)


def test_builtin_workflow_recipes_load_and_validate():
    recipes = list_workflow_recipes()

    recipe_ids = {recipe.id for recipe in recipes}
    assert {
        "text2img-default",
        "zimage-lora",
        "mock-smoke",
        "publish-candidate",
    }.issubset(recipe_ids)

    mock_recipe = get_workflow_recipe("mock-smoke")
    assert mock_recipe.version == 1
    assert mock_recipe.backend_preference == "mock"
    assert mock_recipe.prompt_strategy["type"] == "fixed"


def test_resolve_workflow_recipe_returns_job_payload_with_metadata():
    resolution = resolve_workflow_recipe(
        "mock-smoke",
        seed=12,
        metadata={"client": "test"},
    )

    payload = resolution.to_job_payload(client_request_id="req-recipe-1")
    assert payload["prompt"] == "DreamGen mock smoke test image"
    assert payload["seed"] == 12
    assert payload["client_request_id"] == "req-recipe-1"
    assert payload["recipe_id"] == "mock-smoke"
    assert payload["recipe_version"] == 1
    assert payload["metadata"]["recipe"]["id"] == "mock-smoke"
    assert payload["config_overrides"]["model"]["image_backend"] == "mock"
    assert payload["config_overrides"]["image"]["width"] == 512


def test_apply_config_overrides_temporarily_updates_runtime_config():
    config = MagicMock()
    config.model.image_backend = "auto"
    config.model.ollama_image_model = ""
    config.model.lora.enabled_loras = ["existing"]
    config.model.lora.application_probability = 0.5
    config.image.width = 1360
    config.image.height = 768
    config.image.num_inference_steps = 4
    config.image.guidance_scale = 0.0
    config.image.true_cfg_scale = 1.0

    original_plugins = {name: info.enabled for name, info in plugin_manager.plugins.items()}

    with apply_config_overrides(
        config,
        {
            "model": {"image_backend": "mock"},
            "image": {"width": 512, "height": 512},
            "lora": {"enabled_loras": [], "application_probability": 0.0},
            "plugins": {"enabled": []},
        },
    ):
        assert config.model.image_backend == "mock"
        assert config.image.width == 512
        assert config.image.height == 512
        assert config.model.lora.enabled_loras == []
        assert config.model.lora.application_probability == 0.0
        assert all(not info.enabled for info in plugin_manager.plugins.values())

    assert config.model.image_backend == "auto"
    assert config.image.width == 1360
    assert config.image.height == 768
    assert config.model.lora.enabled_loras == ["existing"]
    assert config.model.lora.application_probability == 0.5
    assert {name: info.enabled for name, info in plugin_manager.plugins.items()} == original_plugins
