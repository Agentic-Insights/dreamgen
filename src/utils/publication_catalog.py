"""Backend-managed publication catalog for generated gallery assets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from src.utils.storage import read_image_metadata

CATALOG_FILENAME = ".gallery_catalog.json"
CATALOG_VERSION = 2
PUBLICATION_STATES = {"draft", "published", "hidden", "featured", "rejected"}
PUBLIC_GALLERY_STATES = {"published", "featured"}
PUBLICATION_BLOCKING_QUALITY_FLAGS = {
    "corrupt",
    "diagnostic",
    "draft",
    "placeholder",
    "provisional",
    "rejected",
    "unsafe",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def utc_now() -> str:
    """Return the current UTC timestamp in API-friendly ISO format."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def catalog_path_for(output_dir: Path) -> Path:
    """Return the catalog path for an output directory."""
    return output_dir / CATALOG_FILENAME


def image_key(image_path: Path, output_dir: Path) -> str:
    """Return a stable, slash-separated catalog key for an image."""
    return image_path.resolve().relative_to(output_dir.resolve()).as_posix()


def image_id_for(key: str) -> str:
    """Return a stable short ID for a catalog key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def default_catalog() -> dict[str, Any]:
    """Return a new empty catalog document."""
    return {"version": CATALOG_VERSION, "updated_at": utc_now(), "assets": {}}


def load_catalog(output_dir: Path) -> dict[str, Any]:
    """Load the publication catalog, returning an empty catalog when absent."""
    path = catalog_path_for(output_dir)
    if not path.exists():
        return default_catalog()

    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_catalog()

    if not isinstance(catalog, dict):
        return default_catalog()
    assets = catalog.get("assets")
    if not isinstance(assets, dict):
        catalog["assets"] = {}
    catalog.setdefault("version", CATALOG_VERSION)
    catalog.setdefault("updated_at", utc_now())
    return catalog


def save_catalog(output_dir: Path, catalog: dict[str, Any]) -> Path:
    """Persist the publication catalog atomically enough for local operator use."""
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog["version"] = CATALOG_VERSION
    catalog["updated_at"] = utc_now()

    path = catalog_path_for(output_dir)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
    return path


def is_placeholder_artifact(image_file: Path, metadata: dict[str, Any] | None = None) -> bool:
    """Return True for mock/test artifacts that should not be public by default."""
    metadata = metadata or read_image_metadata(image_file)
    backend = str(metadata.get("backend", "")).lower()
    if backend == "mock" or metadata.get("is_placeholder") is True:
        return True

    try:
        file_size = image_file.stat().st_size
    except OSError:
        return False

    if file_size > 8 * 1024:
        return False

    try:
        with Image.open(image_file) as img:
            extrema = img.convert("RGB").getextrema()
    except Exception:
        return False

    return all(channel_min == channel_max for channel_min, channel_max in extrema)


def prompt_for(image_path: Path) -> str:
    """Read the prompt sidecar for an image when available."""
    prompt_path = image_path.with_suffix(".txt")
    if not prompt_path.exists():
        return ""

    try:
        return prompt_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def created_at_for(image_path: Path) -> str:
    """Return an image creation timestamp from file metadata."""
    try:
        return datetime.fromtimestamp(image_path.stat().st_mtime).isoformat()
    except OSError:
        return utc_now()


def build_catalog_entry(
    image_path: Path,
    output_dir: Path,
    *,
    prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
    publication_state: str = "draft",
) -> dict[str, Any]:
    """Build a normalized catalog entry for an image."""
    key = image_key(image_path, output_dir)
    metadata = metadata or read_image_metadata(image_path)
    placeholder = is_placeholder_artifact(image_path, metadata)
    state = normalize_publication_state(publication_state)
    if placeholder and state in (PUBLIC_GALLERY_STATES | {"draft"}):
        state = "rejected"

    experiment_metadata = metadata.get("experiment")
    if not isinstance(experiment_metadata, dict):
        experiment_metadata = {}
    metadata_flags = metadata.get("quality_flags") or experiment_metadata.get("quality_flags", [])
    if isinstance(metadata_flags, str):
        flag_values = [flag.strip() for flag in metadata_flags.split(",")]
    else:
        flag_values = [str(flag).strip() for flag in metadata_flags]
    quality_flags = sorted({flag for flag in flag_values if flag})
    if placeholder:
        quality_flags = sorted({*quality_flags, "placeholder"})

    now = utc_now()
    return {
        "id": image_id_for(key),
        "path": key,
        "prompt": prompt if prompt is not None else prompt_for(image_path),
        "metadata": metadata,
        "created_at": created_at_for(image_path),
        "updated_at": now,
        "publication_state": state,
        "published_at": now if state in PUBLIC_GALLERY_STATES else None,
        "publication_history": [],
        "publishable": not placeholder,
        "quality_flags": quality_flags,
    }


def normalize_publication_state(state: str) -> str:
    """Validate and normalize a publication state."""
    normalized = state.strip().lower()
    if normalized not in PUBLICATION_STATES:
        raise ValueError(f"Invalid publication state: {state}")
    return normalized


def register_image(
    image_path: Path,
    output_dir: Path,
    *,
    prompt: str | None = None,
    metadata: dict[str, Any] | None = None,
    publication_state: str = "draft",
) -> dict[str, Any]:
    """Add or refresh an image in the catalog."""
    catalog = load_catalog(output_dir)
    key = image_key(image_path, output_dir)
    existing = catalog["assets"].get(key, {})
    state = existing.get("publication_state", publication_state)
    entry = build_catalog_entry(
        image_path,
        output_dir,
        prompt=prompt,
        metadata=metadata,
        publication_state=state,
    )
    if existing:
        entry["published_at"] = existing.get("published_at") or (
            existing.get("updated_at") if state in PUBLIC_GALLERY_STATES else None
        )
        entry["publication_history"] = list(existing.get("publication_history") or [])
    catalog["assets"][key] = entry
    save_catalog(output_dir, catalog)
    return entry


def remove_image(output_dir: Path, key: str) -> bool:
    """Remove an image from the catalog."""
    catalog = load_catalog(output_dir)
    removed = catalog["assets"].pop(key, None) is not None
    if removed:
        save_catalog(output_dir, catalog)
    return removed


def backfill_catalog(
    output_dir: Path,
    *,
    default_state: str = "published",
    include_placeholders: bool = True,
) -> dict[str, Any]:
    """Register existing output images in the catalog."""
    normalize_publication_state(default_state)
    catalog = load_catalog(output_dir)
    added = 0
    refreshed = 0
    skipped = 0

    if not output_dir.exists():
        save_catalog(output_dir, catalog)
        return {"added": added, "refreshed": refreshed, "skipped": skipped, "total": 0}

    image_files = sorted(
        (
            path
            for path in output_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for image_path in image_files:
        metadata = read_image_metadata(image_path)
        placeholder = is_placeholder_artifact(image_path, metadata)
        if placeholder and not include_placeholders:
            skipped += 1
            continue

        key = image_key(image_path, output_dir)
        existing = catalog["assets"].get(key)
        state = existing.get("publication_state", default_state) if existing else default_state
        if placeholder:
            state = existing.get("publication_state", "rejected") if existing else "rejected"

        refreshed_entry = build_catalog_entry(
            image_path,
            output_dir,
            prompt=prompt_for(image_path),
            metadata=metadata,
            publication_state=state,
        )
        if existing:
            refreshed_entry["published_at"] = existing.get("published_at") or (
                existing.get("updated_at") if state in PUBLIC_GALLERY_STATES else None
            )
            refreshed_entry["publication_history"] = list(existing.get("publication_history") or [])
        catalog["assets"][key] = refreshed_entry
        if existing:
            refreshed += 1
        else:
            added += 1

    save_catalog(output_dir, catalog)
    return {
        "added": added,
        "refreshed": refreshed,
        "skipped": skipped,
        "total": len(catalog["assets"]),
    }


def set_publication_state(
    output_dir: Path,
    key: str,
    publication_state: str,
) -> dict[str, Any]:
    """Update the publication state for one catalog entry."""
    state = normalize_publication_state(publication_state)
    catalog = load_catalog(output_dir)
    assets = catalog["assets"]
    entry = assets.get(key)
    if entry is None:
        raise KeyError(key)

    image_path = (output_dir / key).resolve()
    if not image_path.exists():
        raise FileNotFoundError(key)

    metadata = read_image_metadata(image_path)
    placeholder = is_placeholder_artifact(image_path, metadata)
    if placeholder and state in PUBLIC_GALLERY_STATES:
        raise PermissionError("Placeholder images cannot be published.")

    previous_state = str(entry.get("publication_state", "draft"))
    changed_at = utc_now()
    entry["publication_state"] = state
    entry["updated_at"] = changed_at
    history = list(entry.get("publication_history") or [])
    if previous_state != state:
        history.append({"from": previous_state, "to": state, "changed_at": changed_at})
    entry["publication_history"] = history
    if state in PUBLIC_GALLERY_STATES and previous_state not in PUBLIC_GALLERY_STATES:
        entry["published_at"] = changed_at
    elif state not in PUBLIC_GALLERY_STATES and previous_state in PUBLIC_GALLERY_STATES:
        entry["unpublished_at"] = changed_at
    entry["publishable"] = not placeholder
    if state in PUBLIC_GALLERY_STATES:
        flags = set(entry.get("quality_flags", []))
        flags.difference_update({"draft", "provisional"})
        entry["quality_flags"] = sorted(flags)
    if placeholder:
        flags = set(entry.get("quality_flags", []))
        flags.add("placeholder")
        entry["quality_flags"] = sorted(flags)
    assets[key] = entry
    save_catalog(output_dir, catalog)
    return entry


def public_catalog_entries(output_dir: Path) -> list[dict[str, Any]]:
    """Return catalog entries that should be exposed by the gallery API."""
    catalog = load_catalog(output_dir)
    entries = [
        entry
        for entry in catalog["assets"].values()
        if entry.get("publication_state") in PUBLIC_GALLERY_STATES
    ]
    return sorted(entries, key=lambda entry: str(entry.get("created_at", "")), reverse=True)
