"""Durable lifecycle event export with optional OpenTelemetry hooks."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def write_lifecycle_event(metrics_dir: Path, event: dict[str, Any]) -> None:
    """Append one JSON event to the local operator metrics stream."""
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / "generation_events.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, default=str) + "\n")
    _export_otel(event)


def read_lifecycle_events(metrics_dir: Path, limit: int = 100) -> list[dict[str, Any]]:
    path = metrics_dir / "generation_events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return list(reversed(events))


def _export_otel(event: dict[str, Any]) -> None:
    """Export spans only when explicitly enabled and the optional dependency exists."""
    if os.getenv("DREAMGEN_OTEL_ENABLED", "0").lower() not in {"1", "true", "yes"}:
        return
    try:
        from opentelemetry import trace
    except ImportError:
        logger.warning("DREAMGEN_OTEL_ENABLED is set but OpenTelemetry is not installed")
        return

    tracer = trace.get_tracer("dreamgen")
    with tracer.start_as_current_span(
        str(event.get("name") or event.get("type") or "event")
    ) as span:
        for key in ("id", "backend", "model", "duration_ms", "generation_time"):
            value = event.get(key)
            if value is not None:
                span.set_attribute(f"dreamgen.{key}", value)
