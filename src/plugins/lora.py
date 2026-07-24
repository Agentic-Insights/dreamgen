"""
Plugin for loading and managing Lora models.
"""

import json
import logging
import os
import random
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, List, NamedTuple, Optional

from ..utils.config import Config

logger = logging.getLogger(__name__)

DEFAULT_LORA_METADATA_PATH = Path(__file__).resolve().parents[2] / "data" / "lora_metadata.json"
VALID_LORA_KINDS = {"style", "object"}
VALID_TRIGGER_PLACEMENTS = {"suffix", "subject"}


@dataclass(frozen=True)
class LoraMetadata:
    """Prompt semantics and provenance for one local LoRA adapter."""

    name: str
    kind: str
    trigger: str
    trigger_placement: str
    trigger_required: bool
    display_name: str
    source: str | None = None
    base_model: str | None = None


class SelectedLora(NamedTuple):
    """Container for selected Lora information."""

    name: str
    path: Path
    keyword: str  # The keyword that must be used in the prompt
    kind: str = "style"
    trigger_placement: str = "suffix"
    trigger_required: bool = True
    display_name: str | None = None
    source: str | None = None
    base_model: str | None = None


@lru_cache(maxsize=8)
def _load_lora_metadata_file(path: str) -> dict[str, Any]:
    metadata_path = Path(path)
    if not metadata_path.is_file():
        logger.warning("LoRA metadata file not found: %s", metadata_path)
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unable to read LoRA metadata from %s: %s", metadata_path, exc)
        return {}
    loras = payload.get("loras", {})
    if not isinstance(loras, dict):
        logger.warning("LoRA metadata file %s has no valid 'loras' mapping", metadata_path)
        return {}
    return loras


def get_lora_metadata(lora_name: str, metadata_path: Path | None = None) -> LoraMetadata:
    """Load explicit prompt semantics, using a safe style-suffix fallback."""
    resolved_path = metadata_path or Path(
        os.getenv("LORA_METADATA_PATH", str(DEFAULT_LORA_METADATA_PATH))
    )
    raw = _load_lora_metadata_file(str(resolved_path.resolve())).get(lora_name, {})
    if not isinstance(raw, dict):
        raw = {}

    kind = str(raw.get("kind", "style")).strip().lower()
    if kind not in VALID_LORA_KINDS:
        logger.warning("Unknown LoRA kind %r for %s; defaulting to style", kind, lora_name)
        kind = "style"

    default_placement = "suffix" if kind == "style" else "subject"
    trigger_placement = str(raw.get("trigger_placement", default_placement)).strip().lower()
    if trigger_placement not in VALID_TRIGGER_PLACEMENTS:
        logger.warning(
            "Unknown trigger placement %r for %s; defaulting to %s",
            trigger_placement,
            lora_name,
            default_placement,
        )
        trigger_placement = default_placement

    return LoraMetadata(
        name=lora_name,
        kind=kind,
        trigger=str(raw.get("trigger", lora_name)).strip(),
        trigger_placement=trigger_placement,
        trigger_required=bool(raw.get("trigger_required", True)),
        display_name=str(raw.get("display_name", lora_name)).strip(),
        source=str(raw["source"]).strip() if raw.get("source") else None,
        base_model=str(raw["base_model"]).strip() if raw.get("base_model") else None,
    )


def condition_prompt_for_lora(prompt: str, selection: SelectedLora | None) -> str:
    """Apply a LoRA trigger according to its declared prompt role.

    Style triggers are deterministic, unquoted suffixes and never become the
    scene subject. Object triggers identify the visual subject and are placed
    at the front when the draft omitted them.
    """
    clean_prompt = prompt.strip()
    if selection is None or not selection.trigger_required or not selection.keyword.strip():
        return clean_prompt

    trigger = selection.keyword.strip()
    escaped = re.escape(trigger)
    trigger_pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)

    if selection.kind == "object" or selection.trigger_placement == "subject":
        # Quotes invite text rendering. Normalize an existing object token, or
        # place a missing token before the natural-language scene description.
        normalized = re.sub(
            rf"(['\"]){escaped}\1",
            trigger,
            clean_prompt,
            flags=re.IGNORECASE,
        )
        if trigger_pattern.search(normalized):
            return normalized
        return f"{trigger}, {normalized}" if normalized else trigger

    # Normalize any already-present terminal trigger and append the canonical
    # `, trigger` suffix recommended by style-LoRA model cards.
    terminal_trigger = re.compile(
        rf"(?:,\s*|\s+)(?:['\"])?{escaped}(?:['\"])?[.!]?\s*$",
        re.IGNORECASE,
    )
    scene_prompt = terminal_trigger.sub("", clean_prompt).rstrip(" ,.;:")
    inline_style_trigger = re.compile(
        rf"(?<!\w)(?:['\"])?{escaped}(?:['\"])?(?!\w)",
        re.IGNORECASE,
    )
    if inline_style_trigger.search(scene_prompt):
        logger.warning(
            "Removed inline style trigger %r before appending its conditioning suffix",
            trigger,
        )
        scene_prompt = inline_style_trigger.sub("", scene_prompt)
        scene_prompt = re.sub(r"\s+([,.;:])", r"\1", scene_prompt)
        scene_prompt = re.sub(r"\s{2,}", " ", scene_prompt).strip(" ,;:")
    return f"{scene_prompt}, {trigger}" if scene_prompt else trigger


def get_available_loras(lora_dir: Path) -> List[str]:
    """Get list of available Lora models in the specified directory."""
    if not lora_dir.exists():
        logger.warning(f"Lora directory not found: {lora_dir}")
        return []

    # Look for subdirectories that contain .safetensors files
    lora_names = []
    for subdir in lora_dir.iterdir():
        if subdir.is_dir():
            if list(subdir.glob("*.safetensors")):
                lora_names.append(subdir.name)
                logger.info(f"Found Lora directory: {subdir.name}")

    logger.info(f"Found {len(lora_names)} Lora directories in {lora_dir}")
    return lora_names


def get_lora_path(lora_name: str, config: Config) -> Optional[Path]:
    """Get the full path to a Lora model file."""
    lora_dir = config.model.lora.lora_dir / lora_name

    if not lora_dir.exists():
        logger.warning(f"Lora directory not found: {lora_dir}")
        return None

    # Get all .safetensors files in the directory
    lora_files = list(lora_dir.glob("*.safetensors"))
    if not lora_files:
        logger.warning(f"No .safetensors files found in {lora_dir}")
        return None

    # Sort by version number and get the latest
    latest_lora = sorted(
        lora_files, key=lambda x: int(x.stem.split("-")[-1]) if "-" in x.stem else 0
    )[-1]
    logger.info(f"Selected latest Lora version: {latest_lora}")
    return latest_lora


def get_lora_keyword(lora_name: str) -> str:
    """Get the keyword that must be used in the prompt for this Lora."""
    return get_lora_metadata(lora_name).trigger


def select_random_lora(config: Config) -> Optional[SelectedLora]:
    """
    Randomly select a Lora from enabled Loras based on configuration.
    Returns None if no Lora should be applied based on probability.
    """
    # First check if we should apply a Lora at all
    if random.random() > config.model.lora.application_probability:
        logger.info("Skipping Lora application based on probability")
        return None

    # Get available and enabled Loras
    available_loras = get_available_loras(config.model.lora.lora_dir)
    logger.info(f"Enabled Loras: {config.model.lora.enabled_loras}")
    logger.info(f"Available Loras: {available_loras}")

    enabled_loras = [lora for lora in config.model.lora.enabled_loras if lora in available_loras]

    if not enabled_loras:
        logger.warning("No enabled Loras found in the available Loras list")
        return None

    # Randomly select one Lora
    selected_name = random.choice(enabled_loras)
    selected_path = get_lora_path(selected_name, config)

    if selected_path:
        metadata = get_lora_metadata(selected_name)
        keyword = metadata.trigger
        logger.info(f"Selected Lora: {selected_name} at path: {selected_path}")
        logger.info(
            "LoRA prompt metadata: kind=%s trigger=%r placement=%s required=%s",
            metadata.kind,
            keyword,
            metadata.trigger_placement,
            metadata.trigger_required,
        )
        return SelectedLora(
            name=selected_name,
            path=selected_path,
            keyword=keyword,
            kind=metadata.kind,
            trigger_placement=metadata.trigger_placement,
            trigger_required=metadata.trigger_required,
            display_name=metadata.display_name,
            source=metadata.source,
            base_model=metadata.base_model,
        )

    return None


def apply_lora(config: Config) -> Optional[str]:
    """
    Plugin entry point. Randomly selects a Lora and returns the required keyword
    for the prompt if a Lora is selected.
    """
    selected = select_random_lora(config)
    if selected:
        # Return the keyword that must be used in the prompt
        return selected.keyword
    return None
