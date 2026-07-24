"""Tests for the core ImageGenService boundary."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.plugins.lora import SelectedLora
from src.services import GenerationServiceRequest, ImageGenService
from src.utils.generation_plan import GenerationPlan
from src.utils.plugin_manager import PluginResult
from src.utils.publication_catalog import load_catalog
from src.utils.storage import read_image_metadata


@pytest.fixture
def mock_service_config(tmp_path):
    """Create the minimal config shape used by mock generation."""
    config = MagicMock()
    config.model.image_backend = "mock"
    config.model.flux_model = "black-forest-labs/FLUX.1-schnell"
    config.model.small_sd_model = "segmind/tiny-sd"
    config.model.ollama_model = "prompt-model"
    config.model.lora.lora_dir = tmp_path / "loras"
    config.model.lora.enabled_loras = []
    config.model.lora.application_probability = 0.0
    config.plugins.enabled_plugins = []
    config.plugins.plugin_order = {}
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
    assert result.metadata["model"] == "mock"
    assert result.metadata["generation_time"] >= 0
    assert result.metadata["experiment"]["parameters"]["seed"] == 123
    assert result.metadata["experiment"]["parameters"]["width"] == 64
    assert result.metadata["experiment"]["pipeline"]["resolved_backend"] == "mock"
    assert result.metadata["experiment"]["prompt"]["source"] == "operator"
    assert result.metadata["experiment"]["diagnostic"] is True
    assert "diagnostic" in result.metadata["experiment"]["quality_flags"]
    assert result.metadata["publication"]["state"] == "rejected"
    assert result.metadata["publication"]["quality_flags"] == ["diagnostic", "placeholder"]

    metadata = read_image_metadata(result.image_path)
    assert metadata["backend"] == "mock"
    assert metadata["configured_backend"] == "mock"
    assert metadata["seed"] == 123
    assert metadata["experiment"]["id"]
    assert metadata["quality_flags"] == ["diagnostic"]

    catalog = load_catalog(tmp_path)
    relative_key = result.image_path.relative_to(tmp_path).as_posix()
    assert catalog["assets"][relative_key]["prompt"] == "service boundary test"
    assert catalog["assets"][relative_key]["publication_state"] == "rejected"
    assert catalog["assets"][relative_key]["quality_flags"] == ["diagnostic", "placeholder"]


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
        "generation_plan_resolved",
        "prompt_ready",
        "backend_ready",
        "model_loading",
        "output_path_ready",
        "finalizing_output",
        "generation_completed",
    ]
    assert events[5].payload["output_path"].suffix == ".png"
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


@pytest.mark.asyncio
async def test_service_ad_hoc_output_skips_catalog(mock_service_config, tmp_path):
    gallery_dir = tmp_path / "gallery"
    output_path = tmp_path / "agent" / "result.png"
    service = ImageGenService(mock_service_config, output_dir=gallery_dir)

    result = await service.generate(
        GenerationServiceRequest(
            prompt="ad hoc service test",
            output_path=output_path,
            add_to_gallery=False,
        )
    )

    assert result.image_path == output_path
    assert result.relative_image_path == str(output_path.resolve())
    assert result.publication == {"state": "untracked", "publishable": False}
    assert not (gallery_dir / ".gallery_catalog.json").exists()


@pytest.mark.asyncio
async def test_service_records_resolved_prompt_model(mock_service_config, tmp_path, monkeypatch):
    """Generated prompt metadata should use the model that actually produced it."""

    async def fake_generate_prompt(self, meta_prompt=None):
        self.model_name = "qwen3.5:9b"
        return "generated prompt from resolved model"

    monkeypatch.setattr(
        "src.services.image_generation.PromptGenerator.generate_prompt",
        fake_generate_prompt,
    )

    service = ImageGenService(mock_service_config, output_dir=tmp_path)
    backend = ReusableBackend()

    result = await service.generate(
        GenerationServiceRequest(meta_prompt="probe prompt model"),
        backend=backend,
        backend_name="reusable",
    )

    experiment = result.metadata["experiment"]
    assert experiment["prompt"]["source"] == "generated"
    assert experiment["prompt"]["model"] == "qwen3.5:9b"
    assert experiment["pipeline"]["prompt_model"] == "qwen3.5:9b"


@pytest.mark.asyncio
async def test_service_shares_locked_lora_and_snapshots_metadata_before_cleanup(
    mock_service_config,
    tmp_path,
    monkeypatch,
):
    lora_path = tmp_path / "loras" / "locked-style" / "epoch-1.safetensors"
    lora_path.parent.mkdir(parents=True)
    lora_path.write_bytes(b"service locked lora")
    selection = SelectedLora("locked-style", lora_path, "locked-trigger")
    plan = GenerationPlan(
        plugin_results=(PluginResult("lora", "locked-trigger", "locked adapter"),),
        plugin_descriptions=("lora: locked adapter",),
        enabled_plugins=("lora",),
        temporal_descriptor="",
        selected_lora=selection,
    )

    monkeypatch.setattr(
        "src.services.image_generation.resolve_generation_plan",
        lambda config, plugins_enabled=True: plan,
    )

    async def generate_locked_prompt(self, meta_prompt=None):
        assert self.generation_plan is plan
        assert meta_prompt == "draft with the locked style"
        return "A moonlit local model lab filled with precise instruments"

    monkeypatch.setattr(
        "src.services.image_generation.PromptGenerator.generate_prompt",
        generate_locked_prompt,
    )

    class CleanupClearingBackend:
        def __init__(self):
            self.plan = None
            self.last_generation_metadata = {}
            self.cleaned = False

        def set_generation_plan(self, received_plan):
            self.plan = received_plan

        async def generate_image(self, prompt, output_path, force_reinit=False, seed=None):
            assert self.plan is plan
            assert "locked-trigger" in prompt
            assert prompt.endswith(", locked-trigger")
            assert "'locked-trigger'" not in prompt
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 8), color=(40, 60, 80)).save(output_path)
            self.last_generation_metadata = {
                "selected_lora": "locked-style",
                "selected_lora_path": str(lora_path.resolve()),
                "selected_lora_keyword": "locked-trigger",
                "lora_backend": "diffsynth",
                "seed": seed,
            }
            return output_path, 0.5, "Z-Image-Turbo"

        def cleanup(self):
            self.cleaned = True
            self.last_generation_metadata = {}

    backend = CleanupClearingBackend()
    service = ImageGenService(mock_service_config, output_dir=tmp_path)
    result = await service.generate(
        GenerationServiceRequest(
            meta_prompt="draft with the locked style",
            seed=17,
            cleanup=True,
        ),
        backend=backend,
        backend_name="z-image",
    )

    provenance = result.metadata["lora_provenance"]
    assert backend.cleaned is True
    assert result.metadata["selected_lora"] == "locked-style"
    assert result.metadata["selected_lora_keyword"] == "locked-trigger"
    assert result.metadata["selected_lora_kind"] == "style"
    assert result.prompt.endswith(", locked-trigger")
    assert result.metadata["lora_backend"] == "diffsynth"
    assert provenance["path"] == str(lora_path.resolve())
    assert provenance["sha256"]
    assert result.metadata["generation_plan"]["resolution"] == "once_per_job"
    assert result.metadata["experiment"]["enhancers"]["selected_lora"] == provenance

    catalog = load_catalog(tmp_path)
    relative_key = result.image_path.relative_to(tmp_path).as_posix()
    catalog_metadata = catalog["assets"][relative_key]["metadata"]
    assert catalog_metadata["selected_lora"] == "locked-style"
    assert catalog_metadata["lora_provenance"] == provenance
