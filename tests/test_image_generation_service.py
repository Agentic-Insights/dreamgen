"""Tests for the core ImageGenService boundary."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
        "finalizing_output",
        "generation_completed",
    ]
    assert events[-1].payload["image_path"].startswith("/images/")
