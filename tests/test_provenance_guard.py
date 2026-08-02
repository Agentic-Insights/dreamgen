"""Tests for operational provenance checks."""

from pathlib import Path

from src.plugins.provenance_guard import provenance_guard_post, provenance_guard_pre
from src.utils.plugin_manager import PluginManager


def _plan():
    return {
        "resolution": "once_per_job",
        "plugin_contributions": [
            {"name": "dream_source_mixer", "category": "entropy", "provenance": {"seed": 4}}
        ],
    }


def test_provenance_guard_pre_passes_structured_plan():
    result = provenance_guard_pre({"generation_plan": _plan()})

    assert result["status"] == "passed"
    assert "plugin_contribution_provenance" in result["checks"]


def test_provenance_guard_pre_fails_without_plan_provenance():
    result = provenance_guard_pre(
        {
            "generation_plan": {
                "resolution": "once_per_job",
                "plugin_contributions": [{"name": "legacy", "category": "context"}],
            }
        }
    )

    assert result["status"] == "failed"
    assert "plugin_contribution_provenance" in result["missing"]


def test_provenance_guard_post_marks_missing_output_metadata(tmp_path):
    result = provenance_guard_post(
        {
            "image_path": Path(tmp_path) / "missing.png",
            "final_prompt": "a prompt",
            "backend": "mock",
            "model_name": "mock",
            "generation_plan": _plan(),
        }
    )

    assert result["status"] == "warning"
    assert result["quality_flags"] == ["provenance_incomplete"]


def test_operational_guards_are_not_prompt_contributions():
    manager = PluginManager()
    manager.register("context", "context", lambda: "context", category="context")
    manager.register_guard(
        "provenance_guard",
        "guard",
        pre_hook=lambda context: {"status": "passed"},
    )

    assert [result.name for result in manager.execute_plugins()] == ["context"]
    assert manager.execute_guards("pre", {})[0]["category"] == "operational"
    assert manager.registry_entries()[-1].kind == "guard"
