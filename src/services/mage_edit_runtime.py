"""HTTP client for the isolated local Mage-Flow-Edit sidecar."""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EditRuntimeResult:
    image: bytes
    model: str
    revision: str
    source_revision: str
    elapsed_seconds: float | None
    peak_vram_mb: int | None


def runtime_url() -> str:
    return os.getenv("MAGEFLOW_URL", "http://localhost:25801").rstrip("/")


def probe_edit_runtime(timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{runtime_url()}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def download_edit_model(variant: str, timeout: float = 3600) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{runtime_url()}/edit/models/{variant}/download", data=b"", method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail) from exc


def run_edit(
    image: bytes,
    filename: str,
    settings: dict[str, Any],
    *,
    timeout: float = 900,
) -> EditRuntimeResult:
    boundary = f"dreamgen-{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field(name: str, value: Any) -> None:
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )

    for name in (
        "command",
        "variant",
        "seed",
        "steps",
        "guidance",
        "max_size",
        "negative_prompt",
        "vl_cond_long_edge",
    ):
        field(name, settings[name])
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            image,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        f"{runtime_url()}/edit",
        data=b"".join(parts),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = response.headers
            peak = headers.get("X-DreamGen-Peak-VRAM-MB")
            elapsed = headers.get("X-DreamGen-Elapsed-Seconds")
            return EditRuntimeResult(
                image=response.read(),
                model=headers.get("X-DreamGen-Model", "unknown"),
                revision=headers.get("X-DreamGen-Model-Revision", "unknown"),
                source_revision=headers.get("X-DreamGen-Source-SHA", "unknown"),
                elapsed_seconds=float(elapsed) if elapsed else None,
                peak_vram_mb=int(peak) if peak and peak.isdigit() else None,
            )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = str(parsed.get("detail", detail))
        except json.JSONDecodeError:
            pass
        raise RuntimeError(detail) from exc
