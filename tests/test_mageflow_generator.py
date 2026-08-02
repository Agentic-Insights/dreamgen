"""Focused tests for the isolated Mage-Flow client and readiness contract."""

from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace

from PIL import Image

from src.generators.mageflow_image_generator import MageFlowImageGenerator
from src.utils.mageflow_runtime import mageflow_runtime_ready, probe_mageflow_runtime


class FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self.body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


def config():
    return SimpleNamespace(
        model=SimpleNamespace(
            mageflow_model="microsoft/Mage-Flow",
            mageflow_revision="faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
            mageflow_url="http://mageflow:8001",
            mageflow_steps=20,
            mageflow_cfg=5.0,
            mageflow_timeout_seconds=30,
        ),
        image=SimpleNamespace(height=769, width=1361),
    )


def test_probe_requires_matching_ready_runtime(monkeypatch):
    payload = json.dumps(
        {
            "status": "ready",
            "model_id": "microsoft/Mage-Flow",
            "model_revision": "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
            "loaded": False,
        }
    ).encode()
    monkeypatch.setattr(
        "src.utils.mageflow_runtime.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )

    status = probe_mageflow_runtime("http://mageflow:8001")

    assert status["ready"] is True
    assert status["loaded"] is False
    assert mageflow_runtime_ready("http://mageflow:8001", "microsoft/Mage-Flow") is True
    assert (
        mageflow_runtime_ready(
            "http://mageflow:8001",
            "microsoft/Mage-Flow",
            "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
        )
        is True
    )
    assert (
        mageflow_runtime_ready(
            "http://mageflow:8001",
            "microsoft/Mage-Flow",
            "different-revision",
        )
        is False
    )
    assert mageflow_runtime_ready("http://mageflow:8001", "microsoft/Mage-Flow-Turbo") is False


def test_generator_sends_reproducible_request_and_saves_png(tmp_path, monkeypatch):
    image_buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "navy").save(image_buffer, format="PNG")
    observed = {}

    def urlopen(http_request, timeout):
        observed["url"] = http_request.full_url
        observed["payload"] = json.loads(http_request.data)
        observed["timeout"] = timeout
        return FakeResponse(
            image_buffer.getvalue(),
            {
                "X-DreamGen-Model-Revision": "faca09c18c1c",
                "X-DreamGen-Source-SHA": "6cefeb40e4c8",
            },
        )

    monkeypatch.setattr("src.generators.mageflow_image_generator.request.urlopen", urlopen)
    generator = MageFlowImageGenerator(config())
    output = tmp_path / "mage.png"

    result = asyncio.run(generator.generate_image("A reproducible probe", output, seed=42))

    assert result[0] == output
    assert result[2] == "Mage-Flow"
    assert Image.open(output).size == (16, 16)
    assert observed["url"] == "http://mageflow:8001/generate"
    assert observed["payload"] == {
        "prompt": "A reproducible probe",
        "model_id": "microsoft/Mage-Flow",
        "height": 768,
        "width": 1360,
        "steps": 20,
        "guidance_scale": 5.0,
        "seed": 42,
    }
    assert generator.last_generation_metadata["isolated_runtime"] is True
    assert generator.last_generation_metadata["model_revision"] == "faca09c18c1c"
    assert (
        generator.last_generation_metadata["verified_model_revision"]
        == "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9"
    )
    assert generator.last_generation_metadata["implementation_revision"] == "6cefeb40e4c8"
