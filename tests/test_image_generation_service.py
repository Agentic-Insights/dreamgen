"""Tests for the core ImageGenService boundary."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.services import GenerationServiceRequest, ImageGenService
from src.utils.publication_catalog import load_catalog
from src.utils.storage import read_image_metadata


@pytest.fixture
def mock_service_config(tmp_path):
    """Create the minimal config shape used by mock generation."""
    config = MagicMock()
    config.model.image_backend = "mock"
    config.model.flux_model = "black-forest-labs/FLUX.1-schnell"
    config.model.small_sd_model = "segmind/tiny-sd"
    config.image.width = 64
    config.image.height = 64
    config.system.output_dir = tmp_path
    config.system.cpu_only = True
    return config


class ReusableBackend:
    """Small backend double that proves the service can use caller-owned backends."""

    def __init__(self):
        self.calls = 0
        self.cleaned = False
        self.last_generation_metadata = {"seed_supported": True, "backend_double": True}

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        force_reinit: bool = False,
        seed: int | None = None,
    ) -> tuple[Path, float, str]:
        self.calls += 1
        self.last_generation_metadata["force_reinit"] = force_reinit
        self.last_generation_metadata["seed"] = seed
        Image.new("RGB", (8, 8), color=(20, 40, 60)).save(output_path)
        return output_path, 0.25, "reusable-test-backend"

    def cleanup(self) -> None:
        self.cleaned = True


@pytest.mark.asyncio
async def test_service_generates_image_metadata_and_catalog_entry(mock_service_config, tmp_path):
    service = ImageGenService(mock_service_config, output_dir=tmp_path)

    result = await service.generate(
        GenerationServiceRequest(prompt="service boundary test", seed=123)
    )

    assert result.image_path.exists()
    assert result.relative_image_path.startswith("/images/")
    assert result.backend == "mock"
    assert result.metadata["backend"] == "mock"
    assert result.metadata["seed"] == 123
    assert result.metadata["publication"]["state"] == "rejected"
    assert result.metadata["publication"]["quality_flags"] == ["placeholder"]

    metadata = read_image_metadata(result.image_path)
    assert metadata["backend"] == "mock"
    assert metadata["configured_backend"] == "mock"
    assert metadata["seed"] == 123

    catalog = load_catalog(tmp_path)
    relative_key = result.image_path.relative_to(tmp_path).as_posix()
    assert catalog["assets"][relative_key]["prompt"] == "service boundary test"
    assert catalog["assets"][relative_key]["publication_state"] == "rejected"
    assert catalog["assets"][relative_key]["quality_flags"] == ["placeholder"]


@pytest.mark.asyncio
async def test_service_emits_generation_lifecycle_events(mock_service_config, tmp_path):
    service = ImageGenService(mock_service_config, output_dir=tmp_path)
    events = []

    async def collect(event):
        events.append(event)

    await service.generate(
        GenerationServiceRequest(prompt="event test", seed=7),
        callback=collect,
    )

    event_names = [event.name for event in events]
    assert event_names == [
        "generation_preparing",
        "prompt_ready",
        "backend_ready",
        "model_loading",
        "output_path_ready",
        "finalizing_output",
        "generation_completed",
    ]
    assert events[4].payload["output_path"].suffix == ".png"
    assert events[-1].payload["image_path"].startswith("/images/")


@pytest.mark.asyncio
async def test_service_can_reuse_caller_owned_backend(mock_service_config, tmp_path):
    service = ImageGenService(mock_service_config, output_dir=tmp_path)
    backend = ReusableBackend()

    result = await service.generate(
        GenerationServiceRequest(
            prompt="reused backend test",
            seed=99,
            force_reinit=True,
        ),
        backend=backend,
        backend_name="reusable",
    )

    assert backend.calls == 1
    assert backend.cleaned is False
    assert result.backend == "reusable"
    assert result.model_name == "reusable-test-backend"
    assert result.metadata["backend_double"] is True
    assert result.metadata["force_reinit"] is True
    assert result.metadata["seed"] == 99
