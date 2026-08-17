"""Append-only storage helpers for edit sources, derivatives, and manifests."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def persist_source(output_dir: Path, root_id: str, content: bytes) -> tuple[Path, str]:
    """Persist a normalized source once and return its immutable path and hash."""
    image = Image.open(io.BytesIO(content)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    normalized = buffer.getvalue()
    digest = sha256_bytes(normalized)
    source_dir = output_dir / "edits" / root_id / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"source-{digest[:20]}.png"
    if not path.exists():
        path.write_bytes(normalized)
    return path, digest


def persist_derivative(
    output_dir: Path,
    root_id: str,
    job_id: str,
    version: int,
    content: bytes,
    *,
    command: str,
    metadata: dict[str, Any],
) -> tuple[Path, str]:
    """Write a version-addressed derivative and sidecars without overwriting."""
    digest = sha256_bytes(content)
    version_dir = output_dir / "edits" / root_id / "versions"
    version_dir.mkdir(parents=True, exist_ok=True)
    stem = f"v{version:03d}-{job_id[:8]}-{digest[:20]}"
    path = version_dir / f"{stem}.png"
    if path.exists():
        raise FileExistsError(f"Immutable edit derivative already exists: {path}")
    path.write_bytes(content)
    path.with_suffix(".txt").write_text(command, encoding="utf-8")
    path.with_suffix(".meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    return path, digest


def append_manifest(
    output_dir: Path,
    root_id: str,
    job_id: str,
    version: int,
    payload: dict[str, Any],
) -> tuple[Path, str]:
    """Append an immutable, hash-linked lineage manifest."""
    manifest_dir = output_dir / "edits" / root_id / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(manifest_dir.glob("*.json"))
    previous_sha = sha256_bytes(existing[-1].read_bytes()) if existing else None
    sequence = len(existing) + 1
    manifest = {
        "schema_version": 1,
        "sequence": sequence,
        "recorded_at": utc_now(),
        "previous_manifest_sha256": previous_sha,
        **payload,
    }
    encoded = json.dumps(manifest, indent=2, sort_keys=True, default=str).encode("utf-8")
    digest = sha256_bytes(encoded)
    path = manifest_dir / f"{sequence:04d}-v{version:03d}-{job_id[:8]}-{digest[:16]}.json"
    with path.open("xb") as handle:
        handle.write(encoded)
    return path, digest
