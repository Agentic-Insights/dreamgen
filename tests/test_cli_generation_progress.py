"""Tests for CLI generation progress and diagnostics."""

import asyncio
import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from src.utils import cli
from src.utils.cli import app
from src.utils.publication_catalog import load_catalog

runner = CliRunner()


def test_generate_mock_prints_lifecycle_status(tmp_path, monkeypatch):
    """Mock generation should still expose the lifecycle messages users rely on."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    result = runner.invoke(app, ["generate", "--mock", "--prompt", "test prompt"])

    assert result.exit_code == 0, result.stdout
    assert "Using image backend:" in result.stdout
    assert "resolved: mock" in result.stdout
    assert "Image generation:" in result.stdout
    assert "request submitted" in result.stdout
    assert "Image received and saved" in result.stdout
    assert "Saved to:" in result.stdout

    catalog = load_catalog(tmp_path)
    assert len(catalog["assets"]) == 1


def test_generate_accepts_model_alias_for_backend(tmp_path, monkeypatch):
    """Issue 18 documented --model flux, so keep --model as a backend alias."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    result = runner.invoke(
        app,
        ["generate", "--model", "mock", "--prompt", "test prompt"],
    )

    assert result.exit_code == 0, result.stdout
    assert "requested: mock" in result.stdout
    assert "resolved: mock" in result.stdout


def test_generate_no_gallery_saves_in_current_directory(tmp_path, monkeypatch):
    gallery_dir = tmp_path / "gallery"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(gallery_dir))

    with runner.isolated_filesystem(temp_dir=work_dir):
        result = runner.invoke(
            app, ["generate", "--mock", "--prompt", "ad hoc prompt", "--no-gallery"]
        )
        images = list(Path.cwd().glob("*.png"))

    assert result.exit_code == 0, result.stdout
    assert len(images) == 1
    assert not (gallery_dir / ".gallery_catalog.json").exists()


def test_generate_output_path_implies_no_gallery(tmp_path, monkeypatch):
    gallery_dir = tmp_path / "gallery"
    output_path = tmp_path / "agent-output" / "result.png"
    monkeypatch.setenv("OUTPUT_DIR", str(gallery_dir))

    result = runner.invoke(
        app,
        [
            "generate",
            "--mock",
            "--prompt",
            "agent image",
            "--output",
            str(output_path),
            "--summary-json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert output_path.exists()
    assert output_path.with_suffix(".txt").exists()
    assert output_path.with_suffix(".meta.json").exists()
    assert not (gallery_dir / ".gallery_catalog.json").exists()
    summary_line = next(
        line for line in reversed(result.stdout.splitlines()) if line.startswith("{")
    )
    summary = json.loads(summary_line)
    assert summary["image_path"] == str(output_path)
    assert summary["metadata"]["publication"]["state"] == "untracked"


def test_generate_summary_json_prints_machine_readable_result(tmp_path, monkeypatch):
    """Automation can consume a stable summary after human-readable output."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    result = runner.invoke(
        app,
        ["generate", "--mock", "--prompt", "json summary prompt", "--summary-json"],
    )

    assert result.exit_code == 0, result.stdout
    summary_line = next(
        line for line in reversed(result.stdout.splitlines()) if line.startswith("{")
    )
    summary = json.loads(summary_line)
    assert summary["backend"] == "mock"
    assert summary["prompt"] == "json summary prompt"
    assert summary["image_path"].endswith(".png")
    assert summary["prompt_path"].endswith(".txt")
    assert summary["relative_image_path"].startswith("/images/")


def test_generate_accepts_workflow_recipe(tmp_path, monkeypatch):
    """CLI generation should resolve built-in recipes into generation metadata."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    result = runner.invoke(
        app,
        ["generate", "--recipe", "mock-smoke", "--summary-json"],
    )

    assert result.exit_code == 0, result.stdout
    assert "Using workflow recipe:" in result.stdout
    summary_line = next(
        line for line in reversed(result.stdout.splitlines()) if line.startswith("{")
    )
    summary = json.loads(summary_line)
    assert summary["backend"] == "mock"
    assert summary["prompt"] == "DreamGen mock smoke test image"
    assert summary["metadata"]["recipe"]["id"] == "mock-smoke"
    assert summary["metadata"]["recipe"]["version"] == 1


@pytest.mark.asyncio
async def test_generation_status_emits_heartbeat_for_slow_operation(monkeypatch):
    """Long-running generation should produce periodic visible waiting output."""
    output = StringIO()
    monkeypatch.setattr(
        cli,
        "console",
        Console(file=output, force_terminal=False, color_system=None, width=120),
    )

    result = await cli.await_with_generation_status(
        asyncio.sleep(0.03, result="done"),
        backend_name="flux-schnell",
        phase="Image generation",
        output_path=Path("output.png"),
        heartbeat_seconds=0.01,
    )

    assert result == "done"
    text = output.getvalue()
    assert "request submitted to flux-schnell" in text
    assert "Image generation: waiting on flux-schnell" in text
