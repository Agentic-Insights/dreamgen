"""Contract tests for the isolated Mage-Flow HTTP adapter."""

from __future__ import annotations

import asyncio
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image


def load_sidecar_module():
    module_path = Path(__file__).parents[1] / "mageflow-service" / "app.py"
    spec = importlib.util.spec_from_file_location("dreamgen_mageflow_sidecar", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sidecar():
    return load_sidecar_module()


def generation_request(sidecar, prompt: str = "A red apple on a wooden table"):
    return sidecar.GenerateRequest(
        prompt=prompt,
        model_id=sidecar.MODEL_ID,
        height=512,
        width=512,
        steps=20,
        guidance_scale=5.0,
        seed=42,
    )


def test_cached_snapshot_is_pinned_to_verified_revision(sidecar, monkeypatch):
    observed = {}

    def snapshot_download(**kwargs):
        observed.update(kwargs)
        return f"/models/snapshots/{sidecar.MODEL_REVISION}"

    monkeypatch.setattr(sidecar, "snapshot_download", snapshot_download)

    snapshot = sidecar._cached_snapshot()

    assert snapshot == f"/models/snapshots/{sidecar.MODEL_REVISION}"
    assert observed == {
        "repo_id": "microsoft/Mage-Flow",
        "revision": "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
        "local_files_only": True,
    }


def test_health_requires_checkpoint_cuda_vram_and_compiler(sidecar, monkeypatch):
    snapshot = f"/models/snapshots/{sidecar.MODEL_REVISION}"
    monkeypatch.setattr(sidecar, "_cached_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        sidecar,
        "_cuda_status",
        lambda: {
            "available": True,
            "device": "Test GPU",
            "total_gb": 24.0,
            "sufficient": True,
            "reason": None,
        },
    )
    monkeypatch.setattr(sidecar.shutil, "which", lambda _name: "/usr/bin/cc")
    sidecar._last_error = None
    sidecar._downloading = False
    sidecar._pipeline = None

    payload = sidecar._health_payload()

    assert payload["status"] == "ready"
    assert payload["model_revision"] == sidecar.MODEL_REVISION
    assert payload["verified_model_revision"] == sidecar.MODEL_REVISION
    assert payload["compiler"] == "/usr/bin/cc"


def test_policy_refusal_is_an_explicit_error_not_a_blank_png(sidecar, monkeypatch):
    pipeline = SimpleNamespace(
        model=SimpleNamespace(
            txt_enc=SimpleNamespace(
                screen_text=lambda _prompt: SimpleNamespace(
                    violates=True,
                    categories=["policy"],
                    reason="blocked for test",
                )
            )
        )
    )
    monkeypatch.setattr(sidecar, "_load_pipeline", lambda: pipeline)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(sidecar.generate(generation_request(sidecar)))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["reason"] == "blocked for test"


def test_successful_generation_returns_png_and_pinned_provenance(sidecar, monkeypatch):
    pipeline = SimpleNamespace(
        model=SimpleNamespace(
            txt_enc=SimpleNamespace(
                screen_text=lambda _prompt: SimpleNamespace(
                    violates=False,
                    categories=[],
                    reason="allowed",
                )
            )
        ),
        generate=lambda *_args, **_kwargs: [Image.new("RGB", (512, 512), "red")],
    )
    monkeypatch.setattr(sidecar, "_load_pipeline", lambda: pipeline)
    monkeypatch.setattr(
        sidecar,
        "_cached_snapshot",
        lambda: f"/models/snapshots/{sidecar.MODEL_REVISION}",
    )

    response = asyncio.run(sidecar.generate(generation_request(sidecar)))

    assert response.media_type == "image/png"
    assert response.headers["x-dreamgen-model-revision"] == sidecar.MODEL_REVISION
    assert response.headers["x-dreamgen-source-sha"] == sidecar.SOURCE_SHA
    assert Image.open(io.BytesIO(response.body)).size == (512, 512)


def test_unload_releases_sidecar_pipeline(sidecar, monkeypatch):
    sidecar._pipeline = object()
    monkeypatch.setattr(sidecar.torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(sidecar.torch.cuda, "is_initialized", lambda: False)
    monkeypatch.setattr(sidecar.torch.cuda, "empty_cache", lambda: None)

    payload = sidecar.unload()

    assert payload == {"status": "ready", "unloaded": True, "was_loaded": True}
    assert sidecar._pipeline is None


def test_official_edit_call_uses_only_supported_pipeline_controls(sidecar, monkeypatch):
    observed = {}

    class Pipeline:
        def edit(self, prompts, references, **kwargs):
            observed.update({"prompts": prompts, "references": references, **kwargs})
            return [Image.new("RGB", (64, 64), "teal")]

    monkeypatch.setenv("MAGEFLOW_EDIT_ENABLED", "true")
    monkeypatch.setitem(sidecar.EDIT_MODELS["turbo"], "revision", "a" * 40)
    monkeypatch.setattr(sidecar, "_load_pipeline", lambda *_args: Pipeline())
    monkeypatch.setattr(sidecar.torch.cuda, "is_available", lambda: False)
    source = io.BytesIO()
    Image.new("RGB", (64, 48), "navy").save(source, "PNG")
    second = io.BytesIO()
    Image.new("RGB", (32, 32), "gold").save(second, "PNG")

    image, metrics = sidecar._run_edit(
        [source.getvalue(), second.getvalue()],
        command="make it teal",
        variant="turbo",
        seed=7,
        steps=4,
        guidance=1.0,
        max_size=1024,
        negative_prompt="",
        vl_cond_long_edge=384,
    )

    assert Image.open(io.BytesIO(image)).size == (64, 64)
    assert observed["prompts"] == ["make it teal"]
    assert len(observed["references"]) == 1
    assert len(observed["references"][0]) == 2
    assert all(isinstance(item, Image.Image) for item in observed["references"][0])
    assert observed["seeds"] == [7]
    assert observed["steps"] == 4
    assert observed["cfg"] == 1.0
    assert observed["max_size"] == 1024
    assert observed["vl_cond_long_edge"] == 384
    assert "strength" not in observed
    assert metrics["peak_vram_mb"] is None


def test_official_edit_rejects_more_than_three_references(sidecar):
    with pytest.raises(HTTPException) as exc_info:
        sidecar._run_edit(
            [b"not-read"] * 4,
            command="combine them",
            variant="turbo",
            seed=7,
            steps=4,
            guidance=1.0,
            max_size=1024,
            negative_prompt="",
            vl_cond_long_edge=384,
        )

    assert exc_info.value.status_code == 422
