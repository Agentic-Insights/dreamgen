"""Read-only readiness probes for the isolated local Mage-Flow runtime."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request

MAGEFLOW_SOURCE_URL = "https://github.com/microsoft/Mage"
MAGEFLOW_MODEL_URL = "https://huggingface.co/microsoft/Mage-Flow"
MAGEFLOW_MODEL_REVISION = "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9"


def probe_mageflow_runtime(url: str, timeout: float = 0.75) -> dict[str, Any]:
    """Return the sidecar health payload without raising network errors."""
    health_url = f"{url.rstrip('/')}/health"
    try:
        with request.urlopen(health_url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "reachable": False,
            "status": "runtime_unavailable",
            "ready": False,
            "loaded": False,
            "reason": f"Mage-Flow sidecar is unavailable at {health_url}: {exc}",
        }

    status = str(payload.get("status") or "runtime_unavailable")
    payload.update(
        {
            "reachable": True,
            "status": status,
            "ready": status == "ready",
            "loaded": bool(payload.get("loaded")),
        }
    )
    return payload


def mageflow_runtime_ready(
    url: str,
    model_id: str,
    model_revision: str | None = None,
    timeout: float = 0.75,
) -> bool:
    """Return whether the requested public checkpoint is locally runnable."""
    status = probe_mageflow_runtime(url, timeout=timeout)
    revision_matches = model_revision is None or status.get("model_revision") == model_revision
    return bool(status["ready"] and status.get("model_id") == model_id and revision_matches)
