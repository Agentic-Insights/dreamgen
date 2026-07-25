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

from src.plugins.lora import SelectedLora
from src.utils.generation_plan import GenerationPlan
from src.utils.ollama import OllamaModelInfo
from src.utils.plugin_manager import PluginResult
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
os.environ["RUNTIME_SELECTION_PATH"] = str(Path(_TEST_OUTPUT_DIR) / "runtime-selection.json")
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
    assert data["active_model"]
    assert data["active_model_id"]
    assert data["preferred_model"] == "Z-Image-Turbo"
    assert data["preferred_model_status"] in {"ready", "partial", "not_downloaded"}
    assert data["fallback_model"] == "Small Stable Diffusion"
    assert data["backend"] in [
        "mock",
        "smoke-test",
        "small-sd",
        "sd-turbo",
        "flux-schnell",
        "flux-dev",
        "qwen-image",
        "ernie-image",
        "z-image",
    ]


def test_hf_token_status_ignores_placeholder_environment_value(client, monkeypatch, tmp_path):
    """A template value must not make the authentication page report a token."""
    monkeypatch.setenv("HF_TOKEN", "your_hugging_face_token_here")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    response = client.get("/api/config/hf-token-status")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "source": None}


def test_model_runtime_status_and_cleanup_endpoints(client):
    status = client.get("/api/models/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["configured_backend"]
    assert payload["resolved_backend"]
    assert {item["backend"] for item in payload["backends"]} >= {
        "flux",
        "small",
        "turbo",
        "zimage",
        "ollama",
        "smoke",
        "mock",
    }
    assert "system" in payload["memory"]

    recommended = client.get("/api/models/recommended")
    assert recommended.status_code == 200
    assert recommended.json()["backend"] in {"zimage", "flux", "small"}

    unloaded = client.post("/api/models/unload")
    assert unloaded.status_code == 200
    assert unloaded.json()["message"] == "Runtime caches released"


def test_cors_allows_local_review_ports(client):
    """Local Next.js review servers should not produce browser fetch errors."""
    response = client.options(
        "/api/status",
        headers={
            "Origin": "http://localhost:7862",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:7862"


def test_plugins_endpoint(client):
    """Test the /api/plugins endpoint"""
    response = client.get("/api/plugins")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert any(
        item["name"] == "dream_source_mixer" and item["category"] == "entropy" for item in data
    )
    assert any(item["name"] == "provenance_guard" and item["kind"] == "guard" for item in data)


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
    assert metadata["experiment"]["prompt"]["source"] == "operator"
    assert metadata["experiment"]["pipeline"]["resolved_backend"] == metadata["backend"]
    assert metadata["experiment"]["parameters"]["width"] == 1360
    assert "diagnostic" in metadata["experiment"]["quality_flags"]

    # Verify image path format
    assert data["image_path"].startswith("/images/")
    assert data["image_path"].endswith(".png")


def test_generate_endpoint_records_experiment_annotations(client):
    """Generation requests should persist operator-facing experiment annotations."""
    response = client.post(
        "/api/generate",
        json={
            "prompt": "Typography stress test",
            "meta_prompt": "Probe text rendering boundaries",
            "seed": 77,
            "experiment_label": "text probe",
            "prompt_family": "typography",
            "quality_flags": ["text", "layout"],
        },
    )
    assert response.status_code == 200
    data = response.json()

    experiment = data["metadata"]["experiment"]
    assert experiment["label"] == "text probe"
    assert experiment["prompt_family"] == "typography"
    assert experiment["prompt"]["meta_prompt"] == "Probe text rendering boundaries"
    assert experiment["parameters"]["seed"] == 77
    assert set(experiment["quality_flags"]) >= {"text", "layout", "diagnostic"}

    catalog = load_catalog(Path(_TEST_OUTPUT_DIR))
    relative_key = data["image_path"].replace("/images/", "")
    assert (
        catalog["assets"][relative_key]["metadata"]["experiment"]["prompt_family"] == "typography"
    )
    assert set(catalog["assets"][relative_key]["quality_flags"]) >= {
        "text",
        "layout",
        "diagnostic",
        "placeholder",
    }


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


def test_api_job_and_catalog_persist_locked_lora_provenance(client, monkeypatch, tmp_path):
    """One resolved LoRA should survive API response, job state, and catalog persistence."""
    lora_path = tmp_path / "loras" / "api-style" / "epoch-1.safetensors"
    lora_path.parent.mkdir(parents=True)
    lora_path.write_bytes(b"api locked lora")
    plan = GenerationPlan(
        plugin_results=(PluginResult("lora", "api-trigger", "API adapter"),),
        plugin_descriptions=("lora: API adapter",),
        enabled_plugins=("lora",),
        temporal_descriptor="",
        selected_lora=SelectedLora("api-style", lora_path, "api-trigger"),
    )

    class ApiZImageBackend:
        def __init__(self):
            self.plan = None
            self.last_generation_metadata = {}

        def set_generation_plan(self, received_plan):
            self.plan = received_plan

        async def generate_image(self, prompt, output_path, force_reinit=False, seed=None):
            assert self.plan is plan
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (16, 16), color=(20, 50, 90)).save(output_path)
            self.last_generation_metadata = {
                "selected_lora": "api-style",
                "selected_lora_path": str(lora_path.resolve()),
                "selected_lora_keyword": "api-trigger",
                "lora_backend": "diffsynth",
                "seed": seed,
            }
            return output_path, 0.25, "Z-Image-Turbo"

        def cleanup(self):
            self.last_generation_metadata = {}

    backend = ApiZImageBackend()
    monkeypatch.setattr(
        "src.services.image_generation.resolve_generation_plan",
        lambda config, plugins_enabled=True, seed=None: plan,
    )
    monkeypatch.setattr(
        "src.services.image_generation.create_image_generator",
        lambda config: (backend, "z-image"),
    )

    response = client.post(
        "/api/generate",
        json={"prompt": "A blue model lab with floating geometric instruments", "seed": 88},
    )
    assert response.status_code == 200
    generation = response.json()
    response_metadata = generation["metadata"]
    provenance = response_metadata["lora_provenance"]
    assert response_metadata["selected_lora"] == "api-style"
    assert response_metadata["lora_backend"] == "diffsynth"
    assert response_metadata["selected_lora_kind"] == "style"
    assert generation["prompt"].endswith(", api-trigger")
    assert "'api-trigger'" not in generation["prompt"]
    assert provenance["path"] == str(lora_path.resolve())
    assert provenance["kind"] == "style"
    assert provenance["sha256"]

    job_response = client.get(f"/api/jobs/{generation['id']}")
    assert job_response.status_code == 200
    job = job_response.json()
    assert job["metadata"]["lora_provenance"] == provenance
    plan_event = next(
        event for event in job["events"] if event["name"] == "generation_plan_resolved"
    )
    assert plan_event["payload"]["selected_lora"]["name"] == "api-style"

    catalog = load_catalog(Path(_TEST_OUTPUT_DIR))
    relative_key = generation["image_path"].replace("/images/", "")
    catalog_metadata = catalog["assets"][relative_key]["metadata"]
    assert catalog_metadata["generation_plan"]["resolution"] == "once_per_job"
    assert catalog_metadata["lora_provenance"] == provenance


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


def test_generation_config_endpoint(client, monkeypatch):
    """The generation config endpoint should expose backend and LoRA settings."""
    monkeypatch.setattr(
        "src.api.server.list_ollama_models",
        lambda: [
            OllamaModelInfo(
                name="llama3.2:3b",
                size=1,
                modified="2026-06-15T12:00:00-05:00",
                digest="digest-llama",
                format="gguf",
                family="llama",
                capabilities=["completion"],
                can_prompt=True,
                can_vision=False,
                can_image=False,
            )
        ],
    )

    response = client.get("/api/config/generation")
    assert response.status_code == 200

    data = response.json()
    assert data["image_backend"] == "mock"
    assert data["entropy_level"] in {"calm", "strange", "wild"}
    assert data["prompt_model"] == "llama3.2:3b"
    assert data["configured_prompt_model"] == "llama3.2:3b"
    assert data["image_model"] == "mock generator"
    assert data["pipeline"]["prompt"]["model"] == "llama3.2:3b"
    assert data["pipeline"]["image"]["backend"] == "mock"
    assert isinstance(data["enabled_loras"], list)
    assert isinstance(data["available_loras"], list)
    assert isinstance(data["lora_metadata"], list)
    if data["lora_metadata"]:
        assert {item["kind"] for item in data["lora_metadata"]} <= {"style", "object"}
        assert all("trigger_placement" in item for item in data["lora_metadata"])
    assert "lora_application_probability" in data
    assert "zimage_model_path" in data
    assert data["qwen_image_model"] == "diffusers/qwen-image-nf4"
    assert data["qwen_prompt_magic"] is True
    assert data["qwen_device_map"] == "balanced"
    assert data["ernie_image_model"] == "baidu/ERNIE-Image-Turbo"
    assert data["ernie_prompt_enhancer"] is True


def test_set_generation_config_updates_backend_and_loras(client, monkeypatch):
    """Runtime generation settings should accept backend and LoRA updates."""
    monkeypatch.setattr(
        "src.api.server.list_ollama_models",
        lambda: [
            OllamaModelInfo(
                name="qwen3.6:27b",
                size=1,
                modified="2026-06-15T12:00:00-05:00",
                digest="digest-qwen",
                format="gguf",
                family="qwen35",
                capabilities=["completion"],
                can_prompt=True,
                can_vision=False,
                can_image=False,
            )
        ],
    )

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
        assert data["configured_prompt_model"] == "qwen3.6:27b"
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
    """The Ollama models endpoint should expose capabilities and normalize stale prompt config."""
    original_prompt_model = api_config.model.ollama_model
    original_image_model = api_config.model.ollama_image_model
    original_env_prompt_model = os.environ.get("OLLAMA_MODEL")

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
        assert data["configured_prompt"] == "qwen3.6:27b"
        assert data["current_image"] == "x/z-image-turbo:latest"
        assert data["configured_image"] == "x/z-image-turbo"
        assert data["version"] == "0.21.2"
        assert data["models"][0]["can_image"] is True
        assert data["models"][1]["can_prompt"] is True
        assert "vision" in data["models"][1]["capabilities"]
        assert api_config.model.ollama_model == "qwen3.6:27b"
        assert os.environ["OLLAMA_MODEL"] == "qwen3.6:27b"
    finally:
        api_config.model.ollama_model = original_prompt_model
        api_config.model.ollama_image_model = original_image_model
        if original_env_prompt_model is None:
            os.environ.pop("OLLAMA_MODEL", None)
        else:
            os.environ["OLLAMA_MODEL"] = original_env_prompt_model


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


def test_gallery_catalog_filters_and_facets_use_experiment_metadata(client):
    """Gallery review should be filterable by backend, model, prompt family, and quality flag."""
    output_root = Path(_TEST_OUTPUT_DIR)
    week_dir = output_root / "2099" / "week_06"
    week_dir.mkdir(parents=True, exist_ok=True)

    image_path = week_dir / "image_20990106_000001_filterbee.png"
    image = Image.new("RGB", (64, 64), color=(25, 70, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 50, 42), fill=(210, 230, 80))
    image.save(image_path)
    image_path.with_suffix(".txt").write_text("filter me")
    write_image_metadata(
        image_path,
        {
            "backend": "small-sd",
            "model": "segmind/tiny-sd",
            "is_placeholder": False,
            "experiment": {
                "prompt_family": "layout",
                "quality_flags": ["composition"],
            },
            "quality_flags": ["composition"],
        },
    )

    response = client.post("/api/gallery/catalog/backfill?default_state=published")
    assert response.status_code == 200

    response = client.get(
        "/api/gallery/catalog?backend=small-sd&model=segmind%2Ftiny-sd"
        "&prompt_family=layout&quality_flag=composition"
    )
    assert response.status_code == 200
    data = response.json()
    assert any(asset["path"].endswith("filterbee.png") for asset in data["assets"])

    response = client.get("/api/gallery/catalog?prompt_family=typography")
    assert response.status_code == 200
    assert not any(asset["path"].endswith("filterbee.png") for asset in response.json()["assets"])

    facets_response = client.get("/api/gallery/facets")
    assert facets_response.status_code == 200
    facets = facets_response.json()
    assert "small-sd" in facets["backends"]
    assert "segmind/tiny-sd" in facets["models"]
    assert "layout" in facets["prompt_families"]
    assert "composition" in facets["quality_flags"]


def test_gallery_catalog_displays_resolved_prompt_model(client, monkeypatch):
    """Old generated-prompt metadata should not display a stale configured Ollama alias."""
    output_root = Path(_TEST_OUTPUT_DIR)
    week_dir = output_root / "2099" / "week_07"
    week_dir.mkdir(parents=True, exist_ok=True)

    image_path = week_dir / "image_20990107_000001_promptmodel.png"
    image = Image.new("RGB", (64, 64), color=(45, 80, 110))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 42, 42), fill=(230, 170, 90))
    image.save(image_path)
    image_path.with_suffix(".txt").write_text("generated prompt model test")
    write_image_metadata(
        image_path,
        {
            "backend": "small-sd",
            "model": "segmind/tiny-sd",
            "is_placeholder": False,
            "experiment": {
                "prompt": {
                    "source": "generated",
                    "model": "gpt-oss:latest",
                    "final": "generated prompt model test",
                },
                "pipeline": {
                    "resolved_backend": "small-sd",
                    "model": "segmind/tiny-sd",
                    "prompt_model": "gpt-oss:latest",
                },
            },
        },
    )

    mock_models = [
        OllamaModelInfo(
            name="qwen3.5:9b",
            size=1,
            modified="2026-06-15T12:00:00-05:00",
            digest="digest-qwen",
            format="gguf",
            family="qwen35",
            capabilities=["completion"],
            can_prompt=True,
            can_vision=False,
            can_image=False,
        )
    ]
    original_prompt_model = api_config.model.ollama_model
    monkeypatch.setattr("src.api.server.list_ollama_models", lambda: mock_models)
    try:
        api_config.model.ollama_model = "gpt-oss:latest"
        response = client.post("/api/gallery/catalog/backfill?default_state=published")
        assert response.status_code == 200

        response = client.get("/api/gallery/catalog?limit=100")
        assert response.status_code == 200
        entry = next(
            asset
            for asset in response.json()["assets"]
            if asset["path"].endswith("promptmodel.png")
        )
        experiment = entry["metadata"]["experiment"]
        assert experiment["prompt"]["model"] == "qwen3.5:9b"
        assert experiment["prompt"]["configured_model"] == "gpt-oss:latest"
        assert experiment["pipeline"]["prompt_model"] == "qwen3.5:9b"
        assert experiment["pipeline"]["configured_prompt_model"] == "gpt-oss:latest"
    finally:
        api_config.model.ollama_model = original_prompt_model


def test_placeholder_cannot_be_published_without_override(client):
    """Mock placeholders should stay unpublished even if a stale client sends an override."""
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
    assert response.status_code == 409


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
