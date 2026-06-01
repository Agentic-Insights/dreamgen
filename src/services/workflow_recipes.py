"""Versioned workflow recipes for repeatable generation requests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.plugins import plugin_manager
from src.utils.config import Config

RECIPE_SCHEMA_VERSION = 1
BUILTIN_RECIPE_DIR = Path(__file__).resolve().parents[1] / "recipes"
ALLOWED_RECIPE_MODES = {"text2img"}
ALLOWED_PROMPT_STRATEGIES = {"fixed", "generated"}
CONFIG_IMAGE_KEYS = {
    "width",
    "height",
    "num_inference_steps",
    "guidance_scale",
    "true_cfg_scale",
}


@dataclass(frozen=True)
class WorkflowRecipe:
    """Validated workflow recipe definition."""

    id: str
    version: int
    name: str
    description: str
    mode: str
    backend_preference: str
    prompt_strategy: dict[str, Any]
    image: dict[str, Any] = field(default_factory=dict)
    plugins: dict[str, Any] = field(default_factory=dict)
    lora: dict[str, Any] = field(default_factory=dict)
    publication: dict[str, Any] = field(default_factory=dict)
    post_processing: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowRecipe":
        """Validate and build a recipe from a JSON-compatible dictionary."""
        required = {
            "id",
            "version",
            "name",
            "description",
            "mode",
            "backend_preference",
            "prompt_strategy",
            "publication",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"Recipe is missing required fields: {', '.join(missing)}")

        recipe_id = str(payload["id"]).strip()
        if not recipe_id:
            raise ValueError("Recipe id must not be empty")

        version = int(payload["version"])
        if version < 1:
            raise ValueError(f"Recipe {recipe_id} version must be >= 1")

        mode = str(payload["mode"]).strip()
        if mode not in ALLOWED_RECIPE_MODES:
            raise ValueError(f"Recipe {recipe_id} has unsupported mode: {mode}")

        prompt_strategy = payload["prompt_strategy"]
        if not isinstance(prompt_strategy, dict):
            raise ValueError(f"Recipe {recipe_id} prompt_strategy must be an object")
        strategy_type = str(prompt_strategy.get("type", "")).strip()
        if strategy_type not in ALLOWED_PROMPT_STRATEGIES:
            raise ValueError(f"Recipe {recipe_id} has unsupported prompt strategy: {strategy_type}")
        if strategy_type == "fixed" and not str(prompt_strategy.get("prompt", "")).strip():
            raise ValueError(f"Recipe {recipe_id} fixed prompt strategy requires prompt")

        image = _object_payload(payload, "image", recipe_id)
        unknown_image_keys = sorted(set(image) - CONFIG_IMAGE_KEYS)
        if unknown_image_keys:
            raise ValueError(
                f"Recipe {recipe_id} has unsupported image keys: {', '.join(unknown_image_keys)}"
            )

        return cls(
            id=recipe_id,
            version=version,
            name=str(payload["name"]).strip(),
            description=str(payload["description"]).strip(),
            mode=mode,
            backend_preference=str(payload["backend_preference"]).strip().lower(),
            prompt_strategy=prompt_strategy,
            image=image,
            plugins=_object_payload(payload, "plugins", recipe_id),
            lora=_object_payload(payload, "lora", recipe_id),
            publication=_object_payload(payload, "publication", recipe_id),
            post_processing=_post_processing_payload(payload, recipe_id),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible recipe payload."""
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "backend_preference": self.backend_preference,
            "prompt_strategy": self.prompt_strategy,
            "image": self.image,
            "plugins": self.plugins,
            "lora": self.lora,
            "publication": self.publication,
            "post_processing": self.post_processing,
        }

    def summary(self) -> dict[str, Any]:
        """Return a compact recipe listing payload."""
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "backend_preference": self.backend_preference,
        }

    def config_overrides(self) -> dict[str, Any]:
        """Return runtime config overrides expressed by this recipe."""
        overrides: dict[str, Any] = {
            "model": {"image_backend": self.backend_preference},
            "image": dict(self.image),
        }

        if self.plugins:
            overrides["plugins"] = dict(self.plugins)

        if self.lora:
            overrides["lora"] = dict(self.lora)

        return overrides


@dataclass(frozen=True)
class ResolvedWorkflowRecipe:
    """Recipe resolved into a concrete generation request shape."""

    recipe: WorkflowRecipe
    prompt: str | None
    meta_prompt: str | None
    seed: int | None
    publication_state: str
    metadata: dict[str, Any]
    config_overrides: dict[str, Any]

    def to_job_payload(self, client_request_id: str | None = None) -> dict[str, Any]:
        """Return a JSON-compatible job creation payload."""
        return {
            "prompt": self.prompt,
            "meta_prompt": self.meta_prompt,
            "seed": self.seed,
            "publication_state": self.publication_state,
            "client_request_id": client_request_id,
            "metadata": self.metadata,
            "recipe_id": self.recipe.id,
            "recipe_version": self.recipe.version,
            "config_overrides": self.config_overrides,
        }


def list_workflow_recipes(recipe_dir: Path = BUILTIN_RECIPE_DIR) -> list[WorkflowRecipe]:
    """Load all built-in workflow recipes."""
    recipes = [load_workflow_recipe(path) for path in sorted(recipe_dir.glob("*.json"))]
    return sorted(recipes, key=lambda item: item.id)


def get_workflow_recipe(recipe_id: str, recipe_dir: Path = BUILTIN_RECIPE_DIR) -> WorkflowRecipe:
    """Load one built-in workflow recipe by ID."""
    normalized_id = recipe_id.strip()
    for recipe in list_workflow_recipes(recipe_dir):
        if recipe.id == normalized_id:
            return recipe
    raise KeyError(f"Unknown workflow recipe: {recipe_id}")


def load_workflow_recipe(path: Path) -> WorkflowRecipe:
    """Load and validate one recipe JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Recipe file {path} must contain a JSON object")
    return WorkflowRecipe.from_dict(payload)


def resolve_workflow_recipe(
    recipe_id: str,
    *,
    prompt: str | None = None,
    meta_prompt: str | None = None,
    seed: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResolvedWorkflowRecipe:
    """Resolve a recipe plus caller overrides into a generation request."""
    recipe = get_workflow_recipe(recipe_id)
    strategy = recipe.prompt_strategy
    strategy_type = strategy["type"]

    resolved_prompt = prompt
    resolved_meta_prompt = meta_prompt
    if resolved_prompt is None and strategy_type == "fixed":
        resolved_prompt = str(strategy.get("prompt", "")).strip()
    if resolved_prompt is None and resolved_meta_prompt is None:
        recipe_meta_prompt = strategy.get("meta_prompt")
        if recipe_meta_prompt:
            resolved_meta_prompt = str(recipe_meta_prompt)

    recipe_metadata = {
        **(metadata or {}),
        "recipe": {
            "id": recipe.id,
            "version": recipe.version,
            "mode": recipe.mode,
        },
    }

    return ResolvedWorkflowRecipe(
        recipe=recipe,
        prompt=resolved_prompt,
        meta_prompt=resolved_meta_prompt,
        seed=seed,
        publication_state=str(recipe.publication.get("state", "draft")).strip() or "draft",
        metadata=recipe_metadata,
        config_overrides=recipe.config_overrides(),
    )


@contextmanager
def apply_config_overrides(config: Config, overrides: dict[str, Any] | None) -> Iterator[None]:
    """Temporarily apply recipe runtime overrides to a Config object and plugins."""
    overrides = overrides or {}
    if not overrides:
        yield
        return

    image_values = {key: getattr(config.image, key) for key in CONFIG_IMAGE_KEYS}
    model_values: dict[str, str] = {
        "image_backend": config.model.image_backend,
        "ollama_image_model": config.model.ollama_image_model,
    }
    lora_enabled_loras = list(config.model.lora.enabled_loras)
    lora_application_probability = config.model.lora.application_probability
    plugin_values: dict[str, tuple[bool, int]] = {
        name: (info.enabled, info.order) for name, info in plugin_manager.plugins.items()
    }

    try:
        model_overrides = overrides.get("model") or {}
        if "image_backend" in model_overrides:
            config.model.image_backend = str(model_overrides["image_backend"]).lower()
        if "ollama_image_model" in model_overrides:
            config.model.ollama_image_model = str(model_overrides["ollama_image_model"]).strip()

        image_overrides = overrides.get("image") or {}
        for key in CONFIG_IMAGE_KEYS:
            if key in image_overrides:
                current_value = getattr(config.image, key)
                value = image_overrides[key]
                if isinstance(current_value, int):
                    value = int(value)
                elif isinstance(current_value, float):
                    value = float(value)
                setattr(config.image, key, value)

        lora_overrides = overrides.get("lora") or {}
        if "enabled_loras" in lora_overrides:
            config.model.lora.enabled_loras = [
                str(item).strip() for item in lora_overrides["enabled_loras"] if str(item).strip()
            ]
        if "application_probability" in lora_overrides:
            config.model.lora.application_probability = float(
                lora_overrides["application_probability"]
            )

        plugin_overrides = overrides.get("plugins") or {}
        if "enabled" in plugin_overrides:
            enabled_plugin_names = {str(item).strip() for item in plugin_overrides["enabled"]}
            for name, info in plugin_manager.plugins.items():
                info.enabled = name in enabled_plugin_names

        yield
    finally:
        for key, value in image_values.items():
            setattr(config.image, key, value)
        config.model.image_backend = model_values["image_backend"]
        config.model.ollama_image_model = model_values["ollama_image_model"]
        config.model.lora.enabled_loras = lora_enabled_loras
        config.model.lora.application_probability = lora_application_probability
        for name, (plugin_enabled, order) in plugin_values.items():
            if name in plugin_manager.plugins:
                plugin_manager.plugins[name].enabled = plugin_enabled
                plugin_manager.plugins[name].order = order


def _object_payload(payload: dict[str, Any], key: str, recipe_id: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Recipe {recipe_id} field {key} must be an object")
    return dict(value)


def _post_processing_payload(payload: dict[str, Any], recipe_id: str) -> list[dict[str, Any]]:
    value = payload.get("post_processing", [])
    if not isinstance(value, list):
        raise ValueError(f"Recipe {recipe_id} field post_processing must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Recipe {recipe_id} post_processing entries must be objects")
    return [dict(item) for item in value]
