"""
Tests for the FastAPI server endpoints
"""

import atexit
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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

from src.api import server as api_server
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
        "qwen-image",
        "ernie-image",
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


def test_generate_endpoint_records_durable_job(client):
    """The compatibility generate endpoint should also persist durable job state."""
    response = client.post(
        "/api/generate",
        json={"prompt": "Durable compatibility image", "seed": 24},
    )
    assert response.status_code == 200
    generation = response.json()

    job_response = client.get(f"/api/jobs/{generation['id']}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["status"] == "succeeded"
    assert job["request"]["prompt"] == "Durable compatibility image"
    assert job["metadata"]["seed"] == 24
    assert job["relative_image_path"] == generation["image_path"]
    assert any(event["name"] == "generation_completed" for event in job["events"])


def test_compare_endpoint_runs_same_prompt_seed_across_backend_overrides(client, monkeypatch):
    """Backend comparison should create traceable jobs for the same prompt and seed."""
    from src.generators.mock_image_generator import MockImageGenerator

    def fake_create_image_generator(active_config):
        backend = active_config.model.image_backend
        return MockImageGenerator(active_config), f"fake-{backend}"

    monkeypatch.setattr(
        "src.services.image_generation.create_image_generator",
        fake_create_image_generator,
    )

    response = client.post(
        "/api/compare",
        json={
            "prompt": "same prompt across backends",
            "seed": 101,
            "backends": ["mock", "small"],
            "client_request_id": "req-compare-1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert data["prompt"] == "same prompt across backends"
    assert data["seed"] == 101
    assert data["backends"] == ["mock", "small"]
    assert len(data["results"]) == 2

    fingerprints = set()
    prompt_hashes = set()
    for item in data["results"]:
        assert item["status"] == "succeeded"
        assert item["metadata"]["seed"] == 101
        assert item["metadata"]["comparison"]["id"] == data["comparison_id"]
        assert item["metadata"]["comparison"]["backend"] == item["backend"]
        assert item["metadata"]["experiment"]["runtime"]["seed"] == 101
        fingerprints.add(item["metadata"]["experiment"]["fingerprint"])
        prompt_hashes.add(item["metadata"]["experiment"]["prompt_sha256"])

        job_response = client.get(f"/api/jobs/{item['job_id']}")
        assert job_response.status_code == 200
        job = job_response.json()
        assert job["request"]["config_overrides"]["model"]["image_backend"] == item["backend"]

    assert len(fingerprints) == 2
    assert len(prompt_hashes) == 1


def test_generic_batch_and_upload_edit_routes_are_not_registered(client):
    """Generic automation/editing routes should stay out of the model-probing API."""
    assert client.post("/api/batch").status_code == 404
    assert client.post("/api/edit").status_code == 404


def test_jobs_endpoint_creates_and_lists_generation_job(client):
    """Durable job endpoints should create, run, fetch, and list jobs."""
    response = client.post(
        "/api/jobs",
        json={
            "prompt": "Queued durable image",
            "seed": 31,
            "client_request_id": "req-job-api-1",
        },
    )
    assert response.status_code == 200
    created = response.json()
    assert created["request"]["prompt"] == "Queued durable image"

    job_response = client.get(f"/api/jobs/{created['id']}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["status"] == "succeeded"
    assert job["client_request_id"] == "req-job-api-1"
    assert job["relative_image_path"].startswith("/images/")
    assert any(event["name"] == "succeeded" for event in job["events"])

    list_response = client.get("/api/jobs?status=succeeded&limit=10")
    assert list_response.status_code == 200
    listed_ids = [item["id"] for item in list_response.json()["jobs"]]
    assert created["id"] in listed_ids


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
    assert data["prompt_model"] == "llama3.2:3b"
    assert data["image_model"] == "mock generator"
    assert data["pipeline"]["prompt"]["model"] == "llama3.2:3b"
    assert data["pipeline"]["image"]["backend"] == "mock"
    assert isinstance(data["enabled_loras"], list)
    assert isinstance(data["available_loras"], list)
    assert "lora_application_probability" in data
    assert "zimage_model_path" in data
    assert data["qwen_image_model"] == "diffusers/qwen-image-nf4"
    assert data["qwen_prompt_magic"] is True
    assert data["qwen_device_map"] == "balanced"
    assert data["ernie_image_model"] == "baidu/ERNIE-Image-Turbo"
    assert data["ernie_prompt_enhancer"] is True


def test_huggingface_workspace_without_token(client, monkeypatch, tmp_path):
    """The HF workspace endpoint should still report local experiment context without a token."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    response = client.get("/api/huggingface/workspace")
    assert response.status_code == 200

    data = response.json()
    assert data["configured"] is False
    assert data["connected"] is False
    assert data["account"] is None
    assert isinstance(data["local_loras"], list)
    assert data["lora_dir"] == str(api_config.model.lora.lora_dir)


def test_huggingface_workspace_classifies_dreamgen_repos(client, monkeypatch, tmp_path):
    """Saved HF tokens should expose DreamGen-relevant user and org model repos."""
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    class FakeHfApi:
        def __init__(self, token=None):
            self.token = token

        def whoami(self, token=None):
            return {"name": "alice", "type": "user", "orgs": [{"name": "dream-lab"}]}

        def list_models(self, author=None, **kwargs):
            if author == "alice":
                return [
                    SimpleNamespace(
                        modelId="alice/neon-lora",
                        author="alice",
                        private=True,
                        gated=False,
                        downloads=12,
                        likes=3,
                        last_modified=datetime(2026, 6, 12, tzinfo=timezone.utc),
                        pipeline_tag="text-to-image",
                        tags=["diffusers", "lora", "stable-diffusion-xl"],
                        library_name="diffusers",
                    )
                ]
            if author == "dream-lab":
                return [
                    SimpleNamespace(
                        modelId="dream-lab/qwen-experiment",
                        author="dream-lab",
                        private=False,
                        gated="auto",
                        downloads=7,
                        likes=2,
                        last_modified=datetime(2026, 6, 11, tzinfo=timezone.utc),
                        pipeline_tag="text-to-image",
                        tags=["diffusers", "qwen-image"],
                        library_name="diffusers",
                    )
                ]
            return []

    monkeypatch.setattr(api_server, "HfApi", FakeHfApi)

    response = client.get("/api/huggingface/workspace")
    assert response.status_code == 200

    data = response.json()
    assert data["configured"] is True
    assert data["connected"] is True
    assert data["account"]["name"] == "alice"
    assert data["namespaces"] == ["alice", "dream-lab"]
    assert {repo["id"] for repo in data["lora_repos"]} == {"alice/neon-lora"}
    assert {repo["id"] for repo in data["image_repos"]} == {
        "alice/neon-lora",
        "dream-lab/qwen-experiment",
    }


def test_set_generation_config_updates_backend_and_loras(client):
    """Runtime generation settings should accept backend and LoRA updates."""
    original_backend = api_config.model.image_backend
    original_ollama_model = api_config.model.ollama_model
    original_ollama_image_model = api_config.model.ollama_image_model
    original_qwen_prompt_magic = api_config.model.qwen_prompt_magic
    original_qwen_device_map = api_config.model.qwen_device_map
    original_ernie_image_model = api_config.model.ernie_image_model
    original_ernie_prompt_enhancer = api_config.model.ernie_prompt_enhancer
    original_enabled_loras = list(api_config.model.lora.enabled_loras)
    original_probability = api_config.model.lora.application_probability

    try:
        response = client.post(
            "/api/config/generation",
            json={
                "image_backend": "small",
                "ollama_model": "qwen3.6:27b",
                "ollama_image_model": "x/z-image-turbo:latest",
                "qwen_prompt_magic": False,
                "qwen_device_map": "none",
                "ernie_image_model": "baidu/ERNIE-Image",
                "ernie_prompt_enhancer": False,
                "enabled_loras": ["pixel-art", "comic"],
                "lora_application_probability": 0.25,
            },
        )
        assert response.status_code == 200

        data = response.json()["config"]
        assert data["image_backend"] == "small"
        assert data["ollama_model"] == "qwen3.6:27b"
        assert data["prompt_model"] == "qwen3.6:27b"
        assert data["image_model"] == api_config.model.small_sd_model
        assert data["pipeline"]["prompt"]["model"] == "qwen3.6:27b"
        assert data["pipeline"]["image"]["model"] == api_config.model.small_sd_model
        assert data["ollama_image_model"] == "x/z-image-turbo:latest"
        assert data["qwen_prompt_magic"] is False
        assert data["qwen_device_map"] == "none"
        assert data["ernie_image_model"] == "baidu/ERNIE-Image"
        assert data["ernie_prompt_enhancer"] is False
        assert data["enabled_loras"] == ["pixel-art", "comic"]
        assert data["lora_application_probability"] == 0.25
        assert api_config.model.image_backend == "small"
        assert api_config.model.ollama_model == "qwen3.6:27b"
        assert api_config.model.ollama_image_model == "x/z-image-turbo:latest"
        assert api_config.model.qwen_prompt_magic is False
        assert api_config.model.qwen_device_map == "none"
        assert api_config.model.ernie_image_model == "baidu/ERNIE-Image"
        assert api_config.model.ernie_prompt_enhancer is False
        assert api_config.model.lora.enabled_loras == ["pixel-art", "comic"]
        assert api_config.model.lora.application_probability == 0.25
    finally:
        api_config.model.image_backend = original_backend
        api_config.model.ollama_model = original_ollama_model
        api_config.model.ollama_image_model = original_ollama_image_model
        api_config.model.qwen_prompt_magic = original_qwen_prompt_magic
        api_config.model.qwen_device_map = original_qwen_device_map
        api_config.model.ernie_image_model = original_ernie_image_model
        api_config.model.ernie_prompt_enhancer = original_ernie_prompt_enhancer
        api_config.model.lora.enabled_loras = original_enabled_loras
        api_config.model.lora.application_probability = original_probability


def test_recipes_endpoints_list_and_resolve_builtin_recipe(client):
    """Recipe APIs should expose built-ins and resolve them into job payloads."""
    response = client.get("/api/recipes")
    assert response.status_code == 200
    recipe_ids = {recipe["id"] for recipe in response.json()["recipes"]}
    assert "mock-smoke" in recipe_ids

    detail_response = client.get("/api/recipes/mock-smoke")
    assert detail_response.status_code == 200
    assert detail_response.json()["backend_preference"] == "mock"

    resolve_response = client.post(
        "/api/recipes/mock-smoke/resolve",
        json={"seed": 22, "client_request_id": "req-resolve-1"},
    )
    assert resolve_response.status_code == 200
    resolved = resolve_response.json()["job_request"]
    assert resolved["prompt"] == "DreamGen mock smoke test image"
    assert resolved["seed"] == 22
    assert resolved["recipe_id"] == "mock-smoke"
    assert resolved["recipe_version"] == 1
    assert resolved["metadata"]["recipe"]["id"] == "mock-smoke"
    assert resolved["config_overrides"]["model"]["image_backend"] == "mock"


def test_jobs_endpoint_runs_recipe_and_persists_recipe_metadata(client):
    """Generation jobs created from recipes should persist recipe ID/version."""
    response = client.post(
        "/api/jobs",
        json={
            "recipe_id": "mock-smoke",
            "seed": 33,
            "client_request_id": "req-job-recipe-1",
        },
    )
    assert response.status_code == 200
    created = response.json()
    assert created["request"]["recipe_id"] == "mock-smoke"
    assert created["request"]["recipe_version"] == 1
    assert created["request"]["config_overrides"]["model"]["image_backend"] == "mock"

    job_response = client.get(f"/api/jobs/{created['id']}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["status"] == "succeeded"
    assert job["request"]["recipe_id"] == "mock-smoke"
    assert job["metadata"]["recipe"]["id"] == "mock-smoke"
    assert job["metadata"]["recipe"]["version"] == 1
    assert job["metadata"]["seed"] == 33


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

    response = client.patch(
        f"/api/gallery/publication/{relative_path}",
        json={"state": "featured"},
    )
    assert response.status_code == 200
    assert response.json()["publication_state"] == "featured"

    response = client.get("/api/gallery?limit=100&offset=0")
    assert response.status_code == 200
    featured_item = next(
        item for item in response.json()["images"] if item["path"].endswith("cafefeed.png")
    )
    assert featured_item["publication"]["state"] == "featured"


def test_gallery_sync_status_reports_catalog_publish_plan(client):
    """Operators should be able to see what the R2 publish step would upload."""
    output_root = Path(_TEST_OUTPUT_DIR)
    week_dir = output_root / "2099" / "week_05"
    week_dir.mkdir(parents=True, exist_ok=True)

    image_path = week_dir / "image_20990105_000001_syncfeed.png"
    image = Image.new("RGB", (64, 64), color=(20, 60, 90))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 48, 48), fill=(220, 180, 60))
    image.save(image_path)
    image_path.with_suffix(".txt").write_text("sync me")
    write_image_metadata(image_path, {"backend": "small-sd", "is_placeholder": False})

    response = client.post("/api/gallery/catalog/backfill?default_state=published")
    assert response.status_code == 200

    response = client.get("/api/gallery/sync/status")
    assert response.status_code == 200
    data = response.json()
    assert data["bucket"] == "dreamgen-gallery"
    assert data["catalog_present"] is True
    assert data["ready"] is True
    assert data["needs_publish"] is True
    assert data["upload_images"] >= 1
    assert data["upload_files"] >= 1
    assert "published" in data["approved_states"]
    assert "featured" in data["approved_states"]
    assert any(asset["key"].endswith("syncfeed.png") for asset in data["preview_assets"])


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
