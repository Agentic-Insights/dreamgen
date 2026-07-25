"""Operational provenance checks kept outside prompt composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def provenance_guard_pre(context: dict[str, Any]) -> dict[str, Any]:
    """Validate the locked plan before a renderer is invoked."""
    plan = context.get("generation_plan")
    checks: list[str] = []
    if not isinstance(plan, dict):
        return {"status": "failed", "checks": [], "missing": ["generation_plan"]}
    if plan.get("resolution") != "once_per_job":
        return {"status": "failed", "checks": [], "missing": ["resolution"]}
    checks.append("resolution_once_per_job")
    contributions = plan.get("plugin_contributions")
    if not isinstance(contributions, list):
        return {"status": "failed", "checks": checks, "missing": ["plugin_contributions"]}
    for contribution in contributions:
        if not all(key in contribution for key in ("name", "category", "provenance")):
            return {
                "status": "failed",
                "checks": checks,
                "missing": ["plugin_contribution_provenance"],
            }
    checks.append("plugin_contribution_provenance")
    return {"status": "passed", "checks": checks}


def provenance_guard_post(context: dict[str, Any]) -> dict[str, Any]:
    """Check that the output can be reviewed without requiring secrets or external state."""
    missing: list[str] = []
    image_path = context.get("image_path")
    if not image_path or not Path(image_path).exists():
        missing.append("image_path")
    for key in ("final_prompt", "backend", "model_name", "generation_plan"):
        if context.get(key) in (None, ""):
            missing.append(key)
    return {
        "status": "warning" if missing else "passed",
        "checks": ["output_path", "prompt", "backend", "model", "generation_plan"],
        "quality_flags": ["provenance_incomplete"] if missing else [],
        "missing": missing,
    }
