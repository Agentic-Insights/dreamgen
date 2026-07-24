"""Resolve random plugin and LoRA choices exactly once for a generation run."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from ..plugins import plugin_manager, register_lora_plugin
from ..plugins.lora import SelectedLora, select_random_lora
from .config import Config
from .plugin_manager import PluginResult

logger = logging.getLogger(__name__)


@lru_cache(maxsize=64)
def _sha256_for_file(path: str, size: int, mtime_ns: int) -> str:
    """Hash an immutable file identity, caching by path, size, and mtime."""
    del size, mtime_ns
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lora_provenance(selection: SelectedLora, *, backend: str | None = None) -> dict[str, Any]:
    """Return portable-enough local provenance for one resolved LoRA file."""
    path = selection.path.resolve()
    stat = path.stat()
    return {
        "name": selection.name,
        "display_name": selection.display_name or selection.name,
        "keyword": selection.keyword,
        "kind": selection.kind,
        "trigger_placement": selection.trigger_placement,
        "trigger_required": selection.trigger_required,
        "source": selection.source,
        "base_model": selection.base_model,
        "path": str(path),
        "filename": path.name,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256_for_file(str(path), stat.st_size, stat.st_mtime_ns),
        "backend": backend,
        "selection_source": "job_generation_plan",
    }


def temporal_descriptor_from_results(results: Iterable[PluginResult]) -> str:
    """Build one descriptor without executing any plugin a second time."""
    parts: list[str] = []
    holiday_fact: Any = None
    art_style: Any = None

    for result in results:
        if result.name == "holiday_fact":
            holiday_fact = result.value
        elif result.name == "art_style":
            art_style = result.value
        elif result.name == "lora":
            # A LoRA trigger is conditioning metadata, not temporal or scene
            # prose. Prompt placement is handled from adapter metadata.
            continue
        elif result.value:
            parts.append(str(result.value))

    descriptor = ", ".join(parts)
    if holiday_fact:
        descriptor = f"{descriptor} ({holiday_fact})" if descriptor else f"({holiday_fact})"
    if art_style:
        descriptor = f"{descriptor}, {art_style}" if descriptor else str(art_style)
    return descriptor


@dataclass(frozen=True)
class GenerationPlan:
    """Immutable plugin and adapter choices shared across one generation job."""

    plugin_results: tuple[PluginResult, ...]
    plugin_descriptions: tuple[str, ...]
    enabled_plugins: tuple[str, ...]
    temporal_descriptor: str
    selected_lora: SelectedLora | None = None

    def to_metadata(self, *, lora_backend: str | None = None) -> dict[str, Any]:
        """Serialize the resolved plan for events, jobs, sidecars, and catalog entries."""
        return {
            "resolution": "once_per_job",
            "enabled_plugins": list(self.enabled_plugins),
            "plugin_contributions": [
                {
                    "name": result.name,
                    "value": result.value,
                    "description": result.description,
                }
                for result in self.plugin_results
            ],
            "temporal_descriptor": self.temporal_descriptor,
            "selected_lora": (
                lora_provenance(self.selected_lora, backend=lora_backend)
                if self.selected_lora
                else None
            ),
        }


def resolve_generation_plan(config: Config, *, plugins_enabled: bool = True) -> GenerationPlan:
    """Resolve every enabled plugin and the optional LoRA exactly once."""
    register_lora_plugin(config)
    ordered_plugins = sorted(
        (plugin for plugin in plugin_manager.plugins.values() if plugin.enabled),
        key=lambda plugin: plugin.order,
    )
    enabled_plugins = tuple(plugin.name for plugin in ordered_plugins) if plugins_enabled else ()
    if not plugins_enabled:
        return GenerationPlan((), (), (), "", None)

    selected_lora: SelectedLora | None = None
    overrides: dict[str, Any] = {}
    if "lora" in enabled_plugins:
        try:
            selected_lora = select_random_lora(config)
        except (AttributeError, TypeError) as exc:
            logger.warning("Unable to resolve LoRA selection from this config: %s", exc)
        overrides["lora"] = selected_lora.keyword if selected_lora else None

    results = tuple(plugin_manager.execute_plugins(overrides=overrides))
    descriptions = tuple(plugin_manager.get_plugin_descriptions())
    return GenerationPlan(
        plugin_results=results,
        plugin_descriptions=descriptions,
        enabled_plugins=enabled_plugins,
        temporal_descriptor=temporal_descriptor_from_results(results),
        selected_lora=selected_lora,
    )
