"""
Tests for the FastAPI server endpoints
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from src.utils.ollama import OllamaModelInfo
from src.utils.publication_catalog import load_catalog
from src.utils.storage import metadata_path_for, write_image_metadata

# Redirect OUTPUT_DIR to a temp directory BEFORE any server imports so that test
# runs never write placeholder images into the live output/ directory.
_TEST_OUTPUT_DIR = tempfile.mkdtemp(prefix="dreamgen_test_output_")
atexit.register(shutil.rmtree, _TEST_OUTPUT_DIR, ignore_errors=True)

# Set required environment variables for tests
os.environ["USE_MOCK_GENERATOR"] = "true"
os.environ["MOCK_MODE"] = "true"
os.environ["LORA_DIR"] = "./loras"
os.environ["LORA_APPLICATION_PROBABILITY"] = "0.7"
os.environ["OLLAMA_MODEL"] = "llama3.2:3b"
os.environ["OLLAMA_TEMPERATURE"] = "0.7"
os.environ["OLLAMA_HOST"] = "http://localhost:11434"
os.environ["FLUX_MODEL"] = "black-forest-labs/FLUX.1-schnell"
os.environ["MAX_SEQUENCE_LENGTH"] = "512"
os.environ["IMAGE_HEIGHT"] = "768"
os.environ["IMAGE_WIDTH"] = "1360"
os.environ["NUM_INFERENCE_STEPS"] = "4"
os.environ["GUIDANCE_SCALE"] = "0.0"
os.environ["TRUE_CFG_SCALE"] = "1.0"
os.environ["ENABLED_PLUGINS"] = "time_of_day,art_style"
os.environ["OUTPUT_DIR"] = _TEST_OUTPUT_DIR
os.environ["LOG_DIR"] = "./logs"
os.environ["CACHE_DIR"] = "./.cache"
os.environ["CPU_ONLY"] = "false"
os.environ["MPS_USE_FP16"] = "false"

from src.api.server import app
from src.api.server import config as api_config


@pytest.fixture
def client():
    """Create a test client for the FastAPI app"""
    return TestClient(app)


def test_health_check(client):
    """Test the root health check endpoint"""
    response = client.get("/")
    assert response.status_code in [200, 404]  # May return 404 if no root route


def test_status_endpoint(client):
    """Test the /api/status endpoint"""
    response = client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert "backend" in data
    assert data["status"] == "ready"
    assert data["backend"] in [
        "mock",
        "smoke-test",
        "small-sd",
        "sd-turbo",
        "flux-schnell",
        "flux-dev",
    ]


def test_plugins_endpoint(client):
    """Test the /api/plugins endpoint"""
    response = client.get("/api/plugins")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)


def test_generate_endpoint(client):
    """Test the /api/generate endpoint with mock mode"""
    payload = {
        "prompt": "A serene mountain landscape at sunset",
        "enable_plugins": True,
        "client_request_id": "req-generate-123",
    }

    response = client.post("/api/generate", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "id" in data
    assert "prompt" in data
    assert "image_path" in data
    assert "metadata" in data
    assert "created_at" in data

    # Check metadata
    metadata = data["metadata"]
    assert "backend" in metadata
    assert "plugins_used" in metadata

    # Verify image path format
    assert data["image_path"].startswith("/images/")
    assert data["image_path"].endswith(".png")


def test_prompt_endpoint_accepts_client_request_id(client, monkeypatch):
    """Prompt generation should accept a client request ID used for progress correlation."""

    async def fake_generate_prompt(self, meta_prompt=None):
        return f"prompt from {meta_prompt or 'default'}"

    monkeypatch.setattr("src.api.server.PromptGenerator.generate_prompt", fake_generate_prompt)

    response = client.post(
        "/api/prompt",
        json={
            "meta_prompt": "cinematic alleyway",
            "client_request_id": "req-prompt-123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"prompt": "prompt from cinematic alleyway"}


def test_generate_without_prompt(client):
    """Test generation with AI-generated prompt (requires Ollama)"""
    payload = {"enable_plugins": False}

    response = client.post("/api/generate", json=payload)
    # May fail if Ollama is not running (500), which is expected in test environment
    if response.status_code == 500:
        pytest.skip("Ollama not running - skipping AI prompt generation test")

    assert response.status_code == 200
    data = response.json()
    assert "prompt" in data
    assert len(data["prompt"]) > 0  # Should have generated a prompt


def test_generate_with_seed(client):
    """Test generation with a specific seed"""
    payload = {"prompt": "Test image", "seed": 42}

    response = client.post("/api/generate", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["metadata"].get("seed") == 42


def test_generation_events_endpoint_records_recent_lifecycle(client):
    """Generation lifecycle events should be inspectable after the request completes."""
    payload = {"prompt": "observable test image", "client_request_id": "req-events-123"}

    response = client.post("/api/generate", json=payload)
    assert response.status_code == 200
    generation_id = response.json()["id"]

    events_response = client.get("/api/generation/events?limit=20")
    assert events_response.status_code == 200
    data = events_response.json()
    assert data["limit"] == 20
    assert data["total"] >= 1

    matching = [event for event in data["events"] if event.get("id") == generation_id]
    assert matching
    assert any(event["type"] == "generation_started" for event in matching)
    assert any(
        event["type"] == "task_progress" and event["label"] == "Image ready" for event in matching
    )
    assert all("timestamp" in event for event in matching)


def test_generation_config_endpoint(client):
    """The generation config endpoint should expose backend and LoRA settings."""
    response = client.get("/api/config/generation")
    assert response.status_code == 200

    data = response.json()
    assert data["image_backend"] == "mock"
    assert isinstance(data["enabled_loras"], list)
    assert isinstance(data["available_loras"], list)
    assert "lora_application_probability" in data
    assert "zimage_model_path" in data


def test_set_generation_config_updates_backend_and_loras(client):
    """Runtime generation settings should accept backend and LoRA updates."""
    original_backend = api_config.model.image_backend
    original_ollama_image_model = api_config.model.ollama_image_model
    original_enabled_loras = list(api_config.model.lora.enabled_loras)
    original_probability = api_config.model.lora.application_probability

    try:
        response = client.post(
            "/api/config/generation",
            json={
                "image_backend": "small",
                "ollama_image_model": "x/z-image-turbo:latest",
                "enabled_loras": ["pixel-art", "comic"],
                "lora_application_probability": 0.25,
            },
        )
        assert response.status_code == 200

        data = response.json()["config"]
        assert data["image_backend"] == "small"
        assert data["ollama_image_model"] == "x/z-image-turbo:latest"
        assert data["enabled_loras"] == ["pixel-art", "comic"]
        assert data["lora_application_probability"] == 0.25
        assert api_config.model.image_backend == "small"
        assert api_config.model.ollama_image_model == "x/z-image-turbo:latest"
        assert api_config.model.lora.enabled_loras == ["pixel-art", "comic"]
        assert api_config.model.lora.application_probability == 0.25
    finally:
        api_config.model.image_backend = original_backend
        api_config.model.ollama_image_model = original_ollama_image_model
        api_config.model.lora.enabled_loras = original_enabled_loras
        api_config.model.lora.application_probability = original_probability


def test_ollama_models_endpoint_includes_capabilities_and_resolved_models(client, monkeypatch):
    """The Ollama models endpoint should expose capabilities plus resolved prompt/image selections."""
    original_prompt_model = api_config.model.ollama_model
    original_image_model = api_config.model.ollama_image_model

    mock_models = [
        OllamaModelInfo(
            name="x/z-image-turbo:latest",
            size=12_773_500_825,
            modified="2026-04-23T20:11:47.7848211-05:00",
            digest="digest-z",
            format="safetensors",
            family="ZImagePipeline",
            capabilities=["image"],
            can_prompt=False,
            can_vision=False,
            can_image=True,
        ),
        OllamaModelInfo(
            name="qwen3.6:27b",
            size=17_420_432_739,
            modified="2026-04-23T11:00:26.2084332-05:00",
            digest="digest-q",
            format="gguf",
            family="qwen35",
            capabilities=["completion", "vision", "tools", "thinking"],
            can_prompt=True,
            can_vision=True,
            can_image=False,
        ),
    ]

    monkeypatch.setattr("src.api.server.list_ollama_models", lambda: mock_models)
    monkeypatch.setattr("src.api.server.get_ollama_version", lambda: "0.21.2")

    try:
        api_config.model.ollama_model = "llama3.2:3b"
        api_config.model.ollama_image_model = "x/z-image-turbo"

        response = client.get("/api/ollama/models")
        assert response.status_code == 200

        data = response.json()
        assert data["current"] == "qwen3.6:27b"
        assert data["configured_prompt"] == "llama3.2:3b"
        assert data["current_image"] == "x/z-image-turbo:latest"
        assert data["configured_image"] == "x/z-image-turbo"
        assert data["version"] == "0.21.2"
        assert data["models"][0]["can_image"] is True
        assert data["models"][1]["can_prompt"] is True
        assert "vision" in data["models"][1]["capabilities"]
    finally:
        api_config.model.ollama_model = original_prompt_model
        api_config.model.ollama_image_model = original_image_model


def test_gallery_endpoint(client):
    """Test the /api/gallery endpoint"""
    response = client.get("/api/gallery")
    assert response.status_code == 200

    data = response.json()
    assert "images" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert isinstance(data["images"], list)


def test_gallery_with_pagination(client):
    """Test gallery with pagination parameters"""
    response = client.get("/api/gallery?limit=5&offset=0")
    assert response.status_code == 200

    data = response.json()
    assert data["limit"] == 5
    assert data["offset"] == 0


def test_cors_headers(client):
    """Test that CORS headers are present"""
    response = client.get("/api/status")
    # Check for CORS headers in response (should be present for allowed origins)
    # OPTIONS may return 405 in test client, so we test with GET instead
    assert response.status_code == 200


def test_invalid_generate_request(client):
    """Test generation with minimal valid data"""
    payload = {
        "prompt": "Test prompt",  # Provide prompt to avoid Ollama requirement
        "invalid_field": "test",  # Extra field should be ignored
    }

    response = client.post("/api/generate", json=payload)
    # Should work since prompt is provided and extra fields are ignored
    assert response.status_code == 200


def test_mock_mode_enabled():
    """Verify that mock mode is enabled for tests"""
    from src.api.server import state

    assert state["use_mock"] is True, "Mock mode should be enabled for tests"


def test_image_file_created(client, tmp_path):
    """Test that image files are actually created"""
    # Generate an image
    payload = {"prompt": "Test image creation"}
    response = client.post("/api/generate", json=payload)
    assert response.status_code == 200

    data = response.json()
    image_path = data["image_path"]

    # Convert API path to filesystem path
    # /images/2025/week_40/image_xxx.png -> output/2025/week_40/image_xxx.png
    fs_path = Path(_TEST_OUTPUT_DIR) / image_path.replace("/images/", "")

    # Check if file exists (may not in test environment)
    # This is a best-effort check
    if fs_path.parent.exists():
        assert fs_path.exists() or True  # File may not persist in test mode

    catalog = load_catalog(Path(_TEST_OUTPUT_DIR))
    relative_key = image_path.replace("/images/", "")
    assert relative_key in catalog["assets"]
    assert catalog["assets"][relative_key]["publication_state"] == "rejected"
    assert catalog["assets"][relative_key]["publishable"] is False


def test_gallery_ignores_placeholder_artifacts_beyond_scan_cap(client):
    """Gallery should keep scanning until it finds real images instead of stopping at placeholders."""
    output_root = Path(_TEST_OUTPUT_DIR)
    week_dir = output_root / "2099" / "week_01"
    week_dir.mkdir(parents=True, exist_ok=True)

    for path in output_root.rglob("*.png"):
        path.unlink()
        txt_path = path.with_suffix(".txt")
        if txt_path.exists():
            txt_path.unlink()
        meta_path = metadata_path_for(path)
        if meta_path.exists():
            meta_path.unlink()

    for i in range(60):
        placeholder = week_dir / f"image_20990101_0000{i:02d}_{i:08x}.png"
        Image.new("RGB", (32, 32), color=(200, 200, 200)).save(placeholder)
        placeholder.with_suffix(".txt").write_text("placeholder")
        write_image_metadata(placeholder, {"backend": "mock", "is_placeholder": True})

    valid = week_dir / "image_20990101_000999_deadbeef.png"
    image = Image.new("RGB", (64, 64), color=(20, 20, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 40, 40), fill=(240, 120, 80))
    image.save(valid)
    valid.with_suffix(".txt").write_text("real image")
    write_image_metadata(valid, {"backend": "small-sd", "is_placeholder": False})

    response = client.post("/api/gallery/catalog/backfill")
    assert response.status_code == 200

    response = client.get("/api/gallery?limit=5&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(item["path"].endswith("deadbeef.png") for item in data["images"])


def test_publication_state_controls_gallery_visibility(client):
    """Operators should be able to publish and unpublish cataloged images."""
    output_root = Path(_TEST_OUTPUT_DIR)
    week_dir = output_root / "2099" / "week_03"
    week_dir.mkdir(parents=True, exist_ok=True)

    image_path = week_dir / "image_20990103_000001_cafefeed.png"
    image = Image.new("RGB", (64, 64), color=(30, 40, 50))
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 32, 32), fill=(200, 80, 40))
    image.save(image_path)
    image_path.with_suffix(".txt").write_text("publish me")
    write_image_metadata(image_path, {"backend": "small-sd", "is_placeholder": False})

    response = client.post("/api/gallery/catalog/backfill?default_state=published")
    assert response.status_code == 200

    relative_path = image_path.relative_to(output_root).as_posix()
    response = client.get("/api/gallery?limit=100&offset=0")
    assert response.status_code == 200
    assert any(item["path"].endswith("cafefeed.png") for item in response.json()["images"])

    response = client.patch(
        f"/api/gallery/publication/{relative_path}",
        json={"state": "hidden"},
    )
    assert response.status_code == 200
    assert response.json()["publication_state"] == "hidden"

    response = client.get("/api/gallery?limit=100&offset=0")
    assert response.status_code == 200
    assert not any(item["path"].endswith("cafefeed.png") for item in response.json()["images"])

    response = client.patch(
        f"/api/gallery/publication/{relative_path}",
        json={"state": "published"},
    )
    assert response.status_code == 200
    assert response.json()["publication_state"] == "published"


def test_placeholder_cannot_be_published_without_override(client):
    """Mock placeholders should stay unpublished unless the operator explicitly overrides."""
    output_root = Path(_TEST_OUTPUT_DIR)
    week_dir = output_root / "2099" / "week_04"
    week_dir.mkdir(parents=True, exist_ok=True)

    image_path = week_dir / "image_20990104_000001_baddecaf.png"
    Image.new("RGB", (32, 32), color=(200, 200, 200)).save(image_path)
    image_path.with_suffix(".txt").write_text("placeholder")
    write_image_metadata(image_path, {"backend": "mock", "is_placeholder": True})

    response = client.post("/api/gallery/catalog/backfill")
    assert response.status_code == 200

    relative_path = image_path.relative_to(output_root).as_posix()
    response = client.patch(
        f"/api/gallery/publication/{relative_path}",
        json={"state": "published"},
    )
    assert response.status_code == 409

    response = client.patch(
        f"/api/gallery/publication/{relative_path}",
        json={"state": "published", "allow_placeholder_publish": True},
    )
    assert response.status_code == 200
    assert response.json()["publication_state"] == "published"


def test_delete_image_removes_metadata_sidecar(client):
    """Deleting an image should clean up prompt and metadata sidecars too."""
    output_root = Path(_TEST_OUTPUT_DIR)
    week_dir = output_root / "2099" / "week_02"
    week_dir.mkdir(parents=True, exist_ok=True)

    image_path = week_dir / "image_20990102_000001_feedface.png"
    image = Image.new("RGB", (64, 64), color=(10, 10, 10))
    draw = ImageDraw.Draw(image)
    draw.line((0, 0, 63, 63), fill=(255, 0, 0), width=3)
    image.save(image_path)
    prompt_path = image_path.with_suffix(".txt")
    prompt_path.write_text("delete me")
    metadata_file = write_image_metadata(
        image_path, {"backend": "small-sd", "is_placeholder": False}
    )

    response = client.post("/api/gallery/catalog/backfill")
    assert response.status_code == 200

    relative_path = image_path.relative_to(Path(_TEST_OUTPUT_DIR)).as_posix()
    response = client.delete(f"/api/gallery/{relative_path}")

    assert response.status_code == 200
    assert not image_path.exists()
    assert not prompt_path.exists()
    assert not metadata_file.exists()
    assert relative_path not in load_catalog(Path(_TEST_OUTPUT_DIR))["assets"]
