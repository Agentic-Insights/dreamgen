"""
FastAPI server for Continuous Image Generation
Provides REST API and WebSocket endpoints for the Next.js frontend
"""

import asyncio
import hashlib
import io
import json
import logging
import os
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from src.generators.factory import inspect_local_zimage_model as inspect_zimage_checkpoint
from src.generators.factory import is_model_cached, resolve_image_backend
from src.generators.prompt_generator import PromptGenerator
from src.plugins import plugin_manager, register_lora_plugin
from src.plugins.lora import get_available_loras, get_lora_metadata
from src.services import (
    GenerationJobCreate,
    GenerationProgressEvent,
    ImageGenService,
    SQLiteEditJobStore,
    SQLiteGenerationJobStore,
    append_manifest,
    apply_config_overrides,
    get_workflow_recipe,
    list_workflow_recipes,
    persist_derivative,
    persist_source,
    resolve_workflow_recipe,
    sha256_bytes,
)
from src.services.mage_edit_runtime import download_edit_model, probe_edit_runtime
from src.services.mage_edit_runtime import run_edit as run_mage_edit
from src.services.model_runtime import ModelRuntimeManager
from src.utils.config import Config
from src.utils.gallery_publisher import DEFAULT_BUCKET, build_publish_status
from src.utils.image_engine_catalog import image_engine_catalog
from src.utils.mage_edit import capability_document, get_variant
from src.utils.observability import read_lifecycle_events, write_lifecycle_event
from src.utils.ollama import (
    OllamaModelInfo,
    get_ollama_version,
    list_ollama_models,
    ollama_host,
    resolve_ollama_model,
)
from src.utils.publication_catalog import (
    backfill_catalog,
    catalog_path_for,
    load_catalog,
    public_catalog_entries,
    register_image,
    remove_image,
    set_edit_decision,
    set_publication_state,
)
from src.utils.storage import StorageManager, metadata_path_for, save_image_and_prompt

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_IMAGE_BACKENDS = {
    "auto",
    "mageflow",
    "flux",
    "ollama",
    "zimage",
    "qwen",
    "ernie",
    "small",
    "turbo",
    "smoke",
    "mock",
}
MAX_RECENT_GENERATION_EVENTS = 100
HF_TOKEN_PLACEHOLDER = "your_hugging_face_token_here"


def configured_hf_token() -> str | None:
    """Return a usable Hugging Face token without exposing placeholder values."""
    token = os.getenv("HF_TOKEN", "").strip()
    if not token or token == HF_TOKEN_PLACEHOLDER:
        return None
    return token


# Initialize FastAPI app
app = FastAPI(
    title="DreamGen API",
    description="API for recurring local image generation with plugin-based prompt entropy",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Configure CORS for Next.js frontend
# Get CORS origins from environment variable or use defaults
local_dev_origin_regex = r"http://(localhost|127\.0\.0\.1):\d+"
cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env:
    # Split by comma and strip whitespace
    cors_origins = [origin.strip() for origin in cors_origins_env.split(",")]
else:
    # Default origins for development
    cors_origins = [
        "http://localhost:7860",  # Next.js on custom port
        "http://127.0.0.1:7860",  # Frontend on loopback
        "http://localhost:3000",  # Next.js default dev server
        "http://127.0.0.1:3000",  # Next.js default dev server on loopback
        "http://localhost:3001",  # Alternative port
        "http://127.0.0.1:3001",  # Alternative port on loopback
        "https://dreamgen.agenticinsights.com",  # Production
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=local_dev_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
config = Config()
runtime_manager = ModelRuntimeManager(config)
runtime_manager.load_selection()
state = {
    "configured_backend": config.model.image_backend,
    "use_mock": config.model.image_backend == "mock",
}


def configure_plugins() -> None:
    """Apply config-driven enabled state and ordering to the shared plugin registry."""
    register_lora_plugin(config)

    enabled_plugins = set(config.plugins.enabled_plugins)
    plugin_order = config.plugins.plugin_order

    for name, info in plugin_manager.plugins.items():
        if enabled_plugins:
            info.enabled = name in enabled_plugins
        if name in plugin_order:
            info.order = plugin_order[name]


configure_plugins()


def zimage_native_source_path() -> Path:
    """Return the expected local Z-Image source checkout path."""
    return PROJECT_ROOT / "ref-repos" / "Z-Image" / "src"


def inspect_local_zimage_model(model_path: Path) -> tuple[str, int]:
    """Return readiness status and size for a repo-local Z-Image checkpoint directory."""
    return inspect_zimage_checkpoint(model_path)


def resolved_prompt_model_name() -> str:
    """Return the active completion-capable Ollama model, falling back to configured value."""
    configured_prompt_model = config.model.ollama_model
    try:
        return (
            resolve_prompt_model_from_models(
                list_ollama_models(),
                default_to_configured=True,
            )
            or configured_prompt_model
        )
    except Exception as exc:
        logger.warning("Could not resolve configured Ollama prompt model: %s", exc)
        return configured_prompt_model


def set_configured_prompt_model(model_name: str) -> None:
    """Update the process-wide preferred Ollama prompt model."""
    config.model.ollama_model = model_name
    os.environ["OLLAMA_MODEL"] = model_name
    runtime_manager.persist_selection()


def resolve_prompt_model_from_models(
    models: List[OllamaModelInfo],
    *,
    reconcile_config: bool = False,
    default_to_configured: bool = False,
) -> Optional[str]:
    """Resolve a prompt model and optionally promote the resolved model into config."""
    configured_prompt_model = config.model.ollama_model
    resolved_model = resolve_ollama_model(models, configured_prompt_model, "completion")

    if resolved_model and reconcile_config and resolved_model != configured_prompt_model:
        logger.info(
            "Updating Ollama prompt model config from %s to available local model %s",
            configured_prompt_model,
            resolved_model,
        )
        set_configured_prompt_model(resolved_model)

    if resolved_model:
        return resolved_model

    if default_to_configured:
        return configured_prompt_model

    return None


def generation_config_payload() -> Dict[str, Any]:
    """Serialize mutable generation/runtime settings for the frontend."""
    image_backend = config.model.image_backend
    runtime_status = runtime_manager.status()
    configured_prompt_model = config.model.ollama_model
    prompt_model = resolved_prompt_model_name()

    image_model_by_backend = {
        "auto": "auto resolver",
        "mageflow": config.model.mageflow_model,
        "flux": config.model.flux_model,
        "ollama": config.model.ollama_image_model,
        "zimage": str(config.model.zimage_model_path),
        "qwen": config.model.qwen_image_model,
        "ernie": config.model.ernie_image_model,
        "small": config.model.small_sd_model,
        "turbo": config.model.turbo_model,
        "smoke": config.model.smoke_test_model,
        "mock": "mock generator",
    }
    image_model = image_model_by_backend.get(image_backend, image_backend)
    available_loras = get_available_loras(config.model.lora.lora_dir)
    lora_metadata = [
        {
            "name": metadata.name,
            "display_name": metadata.display_name,
            "kind": metadata.kind,
            "trigger": metadata.trigger,
            "trigger_placement": metadata.trigger_placement,
            "trigger_required": metadata.trigger_required,
            "source": metadata.source,
            "base_model": metadata.base_model,
        }
        for metadata in (get_lora_metadata(name) for name in available_loras)
    ]

    return {
        "width": config.image.width,
        "height": config.image.height,
        "num_inference_steps": config.image.num_inference_steps,
        "guidance_scale": config.image.guidance_scale,
        "true_cfg_scale": config.image.true_cfg_scale,
        "ollama_temperature": config.model.ollama_temperature,
        "ollama_model": configured_prompt_model,
        "prompt_model": prompt_model,
        "configured_prompt_model": configured_prompt_model,
        "image_backend": image_backend,
        "image_model": image_model,
        "resolved_image_backend": runtime_status["resolved_backend"],
        "active_image_model": runtime_status["active_model"],
        "active_image_model_id": runtime_status["active_model_id"],
        "preferred_image_model": runtime_status["preferred_model"],
        "preferred_image_model_status": runtime_status["preferred_model_status"],
        "fallback_reason": runtime_status["fallback_reason"],
        "ollama_image_model": config.model.ollama_image_model,
        "pipeline": {
            "prompt": {
                "provider": "ollama",
                "model": prompt_model,
                "configured_model": configured_prompt_model,
            },
            "image": {
                "backend": image_backend,
                "model": image_model,
            },
        },
        "enabled_loras": config.model.lora.enabled_loras,
        "available_loras": available_loras,
        "lora_metadata": lora_metadata,
        "lora_application_probability": config.model.lora.application_probability,
        "lora_dir": str(config.model.lora.lora_dir),
        "entropy_level": config.plugins.entropy_level,
        "zimage_model_path": str(config.model.zimage_model_path),
        "zimage_native_available": zimage_native_source_path().exists(),
        "mageflow_model": config.model.mageflow_model,
        "mageflow_revision": config.model.mageflow_revision,
        "mageflow_url": config.model.mageflow_url,
        "mageflow_steps": config.model.mageflow_steps,
        "mageflow_cfg": config.model.mageflow_cfg,
        "qwen_image_model": config.model.qwen_image_model,
        "qwen_prompt_magic": config.model.qwen_prompt_magic,
        "qwen_device_map": config.model.qwen_device_map,
        "qwen_lightning": config.model.qwen_lightning,
        "ernie_image_model": config.model.ernie_image_model,
        "ernie_prompt_enhancer": config.model.ernie_prompt_enhancer,
    }


def parse_bool_config(value: Any) -> bool:
    """Parse JSON boolean-like config values from API clients."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


# Output directory setup
OUTPUT_DIR = config.system.output_dir
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files for serving generated images
app.mount("/images", StaticFiles(directory=str(OUTPUT_DIR)), name="images")


MAX_GALLERY_SCAN = int(os.getenv("MAX_GALLERY_SCAN", "2000"))


def normalize_gallery_key(image_path: str) -> str:
    """Normalize API image paths into catalog keys."""
    normalized = image_path.strip().replace("\\", "/").lstrip("/")
    if normalized.startswith("images/"):
        normalized = normalized[len("images/") :]
    return normalized


def metadata_lookup(metadata: Dict[str, Any], key: str) -> Any:
    """Read common experiment fields from either legacy or structured metadata."""
    experiment = metadata.get("experiment") if isinstance(metadata.get("experiment"), dict) else {}
    pipeline = experiment.get("pipeline") if isinstance(experiment.get("pipeline"), dict) else {}
    parameters = (
        experiment.get("parameters") if isinstance(experiment.get("parameters"), dict) else {}
    )

    if key == "backend":
        return metadata.get("backend") or pipeline.get("resolved_backend")
    if key == "model":
        return metadata.get("model") or pipeline.get("model")
    if key == "prompt_family":
        return metadata.get("prompt_family") or experiment.get("prompt_family")
    if key == "seed":
        return metadata.get("seed") or parameters.get("seed")
    return metadata.get(key)


def display_metadata_for_catalog(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Return catalog metadata adjusted for display without mutating sidecars."""
    experiment = metadata.get("experiment")
    if not isinstance(experiment, dict):
        return metadata

    prompt = experiment.get("prompt") if isinstance(experiment.get("prompt"), dict) else {}
    pipeline = experiment.get("pipeline") if isinstance(experiment.get("pipeline"), dict) else {}
    if prompt.get("source") != "generated":
        return metadata

    configured_prompt_model = config.model.ollama_model
    recorded_prompt_model = pipeline.get("prompt_model") or prompt.get("model")
    if recorded_prompt_model != configured_prompt_model:
        return metadata

    resolved_prompt_model = resolved_prompt_model_name()
    if not resolved_prompt_model or resolved_prompt_model == recorded_prompt_model:
        return metadata

    display_metadata = dict(metadata)
    display_experiment = dict(experiment)
    display_prompt = dict(prompt)
    display_pipeline = dict(pipeline)
    display_prompt.setdefault("configured_model", recorded_prompt_model)
    display_prompt["model"] = resolved_prompt_model
    display_pipeline.setdefault("configured_prompt_model", recorded_prompt_model)
    display_pipeline["prompt_model"] = resolved_prompt_model
    display_experiment["prompt"] = display_prompt
    display_experiment["pipeline"] = display_pipeline
    display_experiment["prompt_model_resolution"] = "resolved_from_configured_model"
    display_metadata["experiment"] = display_experiment
    return display_metadata


def matches_gallery_filters(
    entry: Dict[str, Any],
    *,
    backend: Optional[str] = None,
    model: Optional[str] = None,
    prompt_family: Optional[str] = None,
    quality_flag: Optional[str] = None,
    search: Optional[str] = None,
) -> bool:
    """Return whether a catalog entry matches operator review filters."""
    metadata = entry.get("metadata", {})
    if backend and str(metadata_lookup(metadata, "backend")) != backend:
        return False
    if model and str(metadata_lookup(metadata, "model")) != model:
        return False
    if prompt_family and str(metadata_lookup(metadata, "prompt_family")) != prompt_family:
        return False
    if quality_flag:
        flags = {str(flag) for flag in entry.get("quality_flags", [])}
        metadata_flags = metadata.get("quality_flags", [])
        if isinstance(metadata_flags, str):
            flags.update(flag.strip() for flag in metadata_flags.split(",") if flag.strip())
        else:
            flags.update(str(flag).strip() for flag in metadata_flags if str(flag).strip())
        if quality_flag not in flags:
            return False
    if search:
        needle = search.strip().lower()
        searchable = " ".join(
            (
                str(entry.get("path", "")),
                str(entry.get("prompt", "")),
                json.dumps(metadata, sort_keys=True, default=str),
            )
        ).lower()
        if needle not in searchable:
            return False
    return True


def gallery_experiment_facets(entries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Build distinct review filters from catalog metadata."""
    facets = {
        "backends": set(),
        "models": set(),
        "prompt_families": set(),
        "quality_flags": set(),
        "publication_states": set(),
    }
    for entry in entries:
        metadata = entry.get("metadata", {})
        for facet_key, metadata_key in (
            ("backends", "backend"),
            ("models", "model"),
            ("prompt_families", "prompt_family"),
        ):
            value = metadata_lookup(metadata, metadata_key)
            if value not in (None, ""):
                facets[facet_key].add(str(value))
        if entry.get("publication_state"):
            facets["publication_states"].add(str(entry["publication_state"]))
        for flag in entry.get("quality_flags", []):
            if str(flag).strip():
                facets["quality_flags"].add(str(flag))

    return {key: sorted(values) for key, values in facets.items()}


def build_gallery_index(output_dir: Path) -> List[Dict[str, Any]]:
    """Build public gallery metadata from the backend publication catalog."""
    if not catalog_path_for(output_dir).exists():
        backfill_catalog(output_dir, default_state="published", include_placeholders=True)

    images: List[Dict[str, Any]] = []
    last_image: Optional[Dict[str, Any]] = None

    catalog_entries = public_catalog_entries(output_dir)

    for catalog_entry in catalog_entries:
        image_file = output_dir / catalog_entry["path"]
        if not image_file.exists():
            continue

        stat_result = image_file.stat()
        image_entry = {
            "file": image_file,
            "path": f"/images/{image_file.relative_to(output_dir).as_posix()}",
            "created_at": catalog_entry.get(
                "created_at", datetime.fromtimestamp(stat_result.st_mtime).isoformat()
            ),
            "size": stat_result.st_size,
            "prompt_hash": image_file.stem.rsplit("_", 1)[-1],
            "metadata": display_metadata_for_catalog(catalog_entry.get("metadata", {})),
            "publication": {
                "id": catalog_entry.get("id"),
                "state": catalog_entry.get("publication_state"),
                "publishable": catalog_entry.get("publishable", True),
                "quality_flags": catalog_entry.get("quality_flags", []),
            },
        }

        if last_image is not None:
            created_delta = abs(
                (
                    datetime.fromisoformat(last_image["created_at"])
                    - datetime.fromisoformat(image_entry["created_at"])
                ).total_seconds()
            )
            if (
                image_entry["size"] == last_image["size"]
                and image_entry["prompt_hash"] == last_image["prompt_hash"]
                and created_delta <= 8
                and image_entry["metadata"] == last_image["metadata"]
            ):
                continue

        images.append(image_entry)
        last_image = image_entry
        if len(images) >= MAX_GALLERY_SCAN:
            break

    return images


async def hydrate_gallery_entries(images: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Load prompts only for the images being returned to the client."""
    hydrated: List[Dict[str, Any]] = []

    for image_entry in images:
        image_file = image_entry["file"]
        prompt_file = image_file.with_suffix(".txt")
        prompt = ""
        if prompt_file.exists():
            try:
                async with aiofiles.open(prompt_file, "r", encoding="utf-8", errors="ignore") as f:
                    prompt = await f.read()
            except Exception as e:
                logger.warning(f"Failed to read prompt file {prompt_file}: {e}")
                prompt = "Could not read prompt"

        hydrated.append(
            {
                "path": image_entry["path"],
                "prompt": prompt.strip(),
                "created_at": image_entry["created_at"],
                "size": image_entry["size"],
                "metadata": image_entry.get("metadata", {}),
                "publication": image_entry.get("publication", {}),
            }
        )

    return hydrated


# Pydantic models
class GenerateRequest(BaseModel):
    """Request model for image generation"""

    prompt: Optional[str] = Field(None, description="Optional custom prompt")
    meta_prompt: Optional[str] = Field(None, description="Optional prompt-generation steering text")
    enable_plugins: bool = Field(True, description="Enable plugin enhancements")
    seed: Optional[int] = Field(None, description="Random seed for reproducibility")
    recipe_id: Optional[str] = Field(None, description="Optional workflow recipe ID")
    experiment_label: Optional[str] = Field(None, description="Optional operator label for the run")
    prompt_family: Optional[str] = Field(
        None, description="Optional prompt family for review filters"
    )
    quality_flags: List[str] = Field(
        default_factory=list, description="Operator quality flags to attach to this run"
    )
    client_request_id: Optional[str] = Field(
        None, description="Client-provided request ID used to correlate progress events"
    )
    config_overrides: Dict[str, Any] = Field(
        default_factory=dict, description="Optional runtime settings to persist with the job"
    )


class GenerateResponse(BaseModel):
    """Response model for image generation"""

    id: str = Field(..., description="Unique generation ID")
    prompt: str = Field(..., description="Final prompt used")
    image_path: str = Field(..., description="Path to generated image")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Generation metadata")
    created_at: str = Field(..., description="ISO timestamp")


class JobCreateRequest(BaseModel):
    """Request model for durable image generation jobs."""

    prompt: Optional[str] = Field(None, description="Optional custom prompt")
    meta_prompt: Optional[str] = Field(None, description="Optional prompt-generation steering text")
    seed: Optional[int] = Field(None, description="Random seed for reproducibility")
    recipe_id: Optional[str] = Field(None, description="Optional workflow recipe ID")
    publication_state: str = Field("draft", description="Initial publication state")
    experiment_label: Optional[str] = Field(None, description="Optional operator label for the run")
    prompt_family: Optional[str] = Field(
        None, description="Optional prompt family for review filters"
    )
    quality_flags: List[str] = Field(
        default_factory=list, description="Operator quality flags to attach to this run"
    )
    client_request_id: Optional[str] = Field(
        None, description="Client-provided request ID used to correlate progress events"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extra job metadata")
    config_overrides: Dict[str, Any] = Field(
        default_factory=dict, description="Runtime settings to apply for this job"
    )


class PublicationUpdateRequest(BaseModel):
    """Request model for changing gallery publication state."""

    state: str = Field(..., description="Publication state for this image")


class EditRequest(BaseModel):
    """Request model for image editing"""

    prompt: str = Field(..., description="Edit prompt describing desired changes")
    strength: float = Field(0.8, ge=0.0, le=1.0, description="Edit strength (0.0 to 1.0)")
    backend: str = Field("auto", description="Editing backend: auto, mock, or qwen")
    source_path: Optional[str] = Field(None, description="Catalog path of the source image")


class BulkPublicationRequest(BaseModel):
    """Request model for applying one publication state to multiple catalog assets."""

    image_paths: List[str] = Field(..., min_length=1)
    state: str = Field(..., description="Publication state for all selected images")


class PromptRequest(BaseModel):
    """Request model for prompt generation."""

    meta_prompt: Optional[str] = Field(
        None, description="Optional system prompt used to steer prompt generation"
    )
    client_request_id: Optional[str] = Field(
        None, description="Client-provided request ID used to correlate progress events"
    )


class EditResponse(BaseModel):
    """Response model for image editing"""

    id: str = Field(..., description="Unique edit ID")
    prompt: str = Field(..., description="Edit prompt used")
    original_path: str = Field(..., description="Path to original image")
    edited_path: str = Field(..., description="Path to edited image")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Edit metadata")
    created_at: str = Field(..., description="ISO timestamp")


class EditDecisionRequest(BaseModel):
    """Approve or reject one immutable edit derivative."""

    decision: str = Field(..., pattern="^(approved|rejected|pending)$")


class PluginInfo(BaseModel):
    """Plugin information model"""

    name: str
    enabled: bool
    description: str
    order: int
    category: str = "context"
    kind: str = "prompt"
    phase: str = "prompt"


class PluginOrderRequest(BaseModel):
    """Request model for plugin ordering."""

    ordered_names: List[str] = Field(..., description="Plugin names in desired execution order")


class PromptResponse(BaseModel):
    """Response model for prompt generation."""

    prompt: str = Field(..., description="Generated prompt text")


class RecipeResolveRequest(BaseModel):
    """Request model for resolving a workflow recipe into a job payload."""

    prompt: Optional[str] = Field(None, description="Optional prompt override")
    meta_prompt: Optional[str] = Field(None, description="Optional meta-prompt override")
    seed: Optional[int] = Field(None, description="Optional seed override")
    client_request_id: Optional[str] = Field(
        None, description="Client-provided request ID used to correlate progress events"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extra request metadata")


class SystemStatus(BaseModel):
    """System status model"""

    status: str = Field(..., description="System status (ready, busy, error)")
    backend: str = Field(..., description="Active backend (mock, flux)")
    plugins_enabled: bool
    active_plugins: List[str]
    gpu_available: bool
    ollama_available: bool
    configured_backend: str
    resolved_backend: str
    active_backend_label: str
    active_model: str
    active_model_id: str
    active_model_status: str
    preferred_backend: str
    preferred_model: str
    preferred_model_id: str
    preferred_model_status: str
    fallback_backend: str
    fallback_model: str
    fallback_model_id: str
    fallback_reason: Optional[str] = None


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass  # Handle disconnected clients


manager = ConnectionManager()
recent_generation_events: deque[Dict[str, Any]] = deque(maxlen=MAX_RECENT_GENERATION_EVENTS)
generation_job_store = SQLiteGenerationJobStore(OUTPUT_DIR / ".generation_jobs.sqlite3")
edit_job_store = SQLiteEditJobStore(OUTPUT_DIR / ".edit_jobs.sqlite3")
generation_worker_lock = asyncio.Lock()


def record_generation_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Record a lightweight lifecycle event for recent operator diagnostics."""
    payload = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **event,
    }
    recent_generation_events.appendleft(payload)
    write_lifecycle_event(OUTPUT_DIR / "metrics", payload)
    return payload


def edit_capabilities_with_runtime() -> dict[str, Any]:
    """Merge static official capabilities with live, local sidecar state."""
    document = capability_document()
    runtime = probe_edit_runtime()
    if runtime is None:
        document["runtime_status"] = "offline"
        document["runtime_reason"] = "The local Mage-Flow sidecar is not reachable."
        for variant in document["variants"]:
            variant["ready"] = False
        document["available"] = False
        return document

    cuda = runtime.get("cuda") or {}
    document["gpu"] = {
        "available": bool(cuda.get("available")),
        "name": cuda.get("device"),
        "vram_total_mb": round(float(cuda.get("total_gb", 0)) * 1024) or None,
        "vram_free_mb": round(float(cuda.get("free_gb", 0)) * 1024) or None,
    }
    document["model_loaded"] = bool(runtime.get("loaded"))
    document["loaded_model_id"] = runtime.get("loaded_model_id")
    document["runtime_status"] = runtime.get("status", "unknown")
    document["runtime_reason"] = runtime.get("reason")
    runtime_models = runtime.get("edit_models") or {}
    for variant in document["variants"]:
        live = runtime_models.get(variant["id"]) or {}
        variant["cached"] = bool(live.get("cached"))
        variant["ready"] = bool(
            variant["available"] and live.get("available") and live.get("cached")
        )
    document["available"] = any(variant["ready"] for variant in document["variants"])
    return document


async def execute_mage_edit_job(job_id: str, sources: list[tuple[bytes, str]]) -> None:
    """Execute a queued official edit and persist an immutable derivative."""
    job = edit_job_store.start_job(job_id)
    if job.get("status") != "running":
        return
    metadata = dict(job.get("metadata") or {})
    settings = dict(metadata.get("settings") or {})
    try:
        result = await asyncio.to_thread(run_mage_edit, sources, settings)
        if (edit_job_store.get_job(job_id) or {}).get("status") == "cancelling":
            edit_job_store.finish_cancellation(job_id)
            return
        root_id = str(job["root_job_id"])
        version = int(job["version"])
        completed_metadata = {
            **metadata,
            "model": result.model,
            "upstream_model": result.upstream_model,
            "model_revision": result.revision,
            "artifact_path": result.artifact_path,
            "artifact_sha256": result.artifact_sha256,
            "provenance_status": result.provenance_status,
            "configuration_repository": result.configuration_repository,
            "configuration_revision": result.configuration_revision,
            "source_revision": result.source_revision,
            "timing": {"elapsed_seconds": result.elapsed_seconds},
            "hardware": {"peak_vram_mb": result.peak_vram_mb},
            "edit_lineage": {
                **dict(metadata.get("edit_lineage") or {}),
                "role": "derivative",
                "decision_state": "pending",
            },
        }
        derivative_sha = sha256_bytes(result.image)
        completed_metadata["derivative_sha256"] = derivative_sha
        derivative_path, derivative_sha = persist_derivative(
            OUTPUT_DIR,
            root_id,
            job_id,
            version,
            result.image,
            command=job["prompt"],
            metadata=completed_metadata,
        )
        manifest_path, manifest_sha = append_manifest(
            OUTPUT_DIR,
            root_id,
            job_id,
            version,
            {
                "event": "created",
                "job_id": job_id,
                "root_job_id": root_id,
                "parent_job_id": job.get("parent_job_id"),
                "command": job["prompt"],
                "source_sha256": metadata.get("source_sha256"),
                "source_sha256s": metadata.get("source_sha256s"),
                "source_artifacts": metadata.get("source_artifacts"),
                "derivative_sha256": derivative_sha,
                "model": result.model,
                "upstream_model": result.upstream_model,
                "model_revision": result.revision,
                "artifact_path": result.artifact_path,
                "artifact_sha256": result.artifact_sha256,
                "provenance_status": result.provenance_status,
                "configuration_repository": result.configuration_repository,
                "configuration_revision": result.configuration_revision,
                "source_revision": result.source_revision,
                "settings": settings,
                "timing": completed_metadata["timing"],
                "hardware": completed_metadata["hardware"],
                "decision_state": "pending",
            },
        )
        completed_metadata["manifest_sha256"] = manifest_sha
        relative_source = str(job["source_path"])
        relative_derivative = f"/images/{derivative_path.relative_to(OUTPUT_DIR).as_posix()}"
        register_image(
            derivative_path,
            OUTPUT_DIR,
            prompt=job["prompt"],
            metadata=completed_metadata,
            publication_state="draft",
        )
        edit_job_store.complete_job(
            job_id,
            original_path=relative_source,
            edited_path=relative_derivative,
            metadata=completed_metadata,
        )
        edit_job_store.set_decision(job_id, "pending", manifest_path=str(manifest_path))
        await manager.broadcast(json.dumps({"type": "edit_completed", "id": job_id}))
    except Exception as exc:
        logger.exception("Mage-Flow-Edit job %s failed", job_id)
        edit_job_store.fail_job(job_id, str(exc))
        await manager.broadcast(json.dumps({"type": "edit_error", "id": job_id, "error": str(exc)}))


async def broadcast_task_progress(
    *,
    task: str,
    task_id: str,
    client_request_id: Optional[str],
    progress: int,
    label: str,
    detail: str,
) -> None:
    """Broadcast a normalized task progress event for frontend progress UIs."""
    payload = record_generation_event(
        {
            "type": "task_progress",
            "task": task,
            "id": task_id,
            "client_request_id": client_request_id,
            "progress": progress,
            "label": label,
            "detail": detail,
        }
    )
    await manager.broadcast(json.dumps(payload))


async def emit_generation_service_event(
    *,
    job_id: str,
    client_request_id: Optional[str],
    event: GenerationProgressEvent,
) -> None:
    """Persist and broadcast a service lifecycle event for a durable job."""
    generation_job_store.record_event(job_id, event)
    record_generation_event(
        {
            "type": "generation_lifecycle",
            "name": event.name,
            "id": job_id,
            "client_request_id": client_request_id,
            "progress": event.progress,
            "label": event.label,
            "detail": event.detail,
            "payload": event.payload,
            "duration_ms": event.duration_ms,
        }
    )
    if event.progress is not None:
        await broadcast_task_progress(
            task="image_generation",
            task_id=job_id,
            client_request_id=client_request_id,
            progress=event.progress,
            label=event.label or event.name,
            detail=event.detail or "",
        )

    if event.name == "prompt_generated":
        await manager.broadcast(
            json.dumps(
                {
                    "type": "prompt_generated",
                    "id": job_id,
                    "client_request_id": client_request_id,
                    "prompt": event.payload.get("prompt", ""),
                }
            )
        )
    elif event.name == "model_loading":
        await manager.broadcast(
            json.dumps(
                {
                    "type": "model_loading",
                    "id": job_id,
                    "client_request_id": client_request_id,
                    "message": event.payload.get("message", event.detail or ""),
                }
            )
        )
    elif event.name == "generation_completed":
        await manager.broadcast(
            json.dumps(
                {
                    "type": "generation_completed",
                    "id": job_id,
                    "client_request_id": client_request_id,
                    "image_path": event.payload.get("image_path", ""),
                    "prompt": event.payload.get("prompt", ""),
                }
            )
        )


async def run_generation_job(job_id: str):
    """Run one queued generation job through the shared service boundary."""
    job_payload = generation_job_store.request_for_job(job_id)
    if job_payload is None:
        raise KeyError(f"Unknown generation job: {job_id}")

    async with generation_worker_lock:
        current = generation_job_store.get_job(job_id)
        if current is None:
            raise KeyError(f"Unknown generation job: {job_id}")
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            return None

        generation_job_store.start_job(job_id)
        await manager.broadcast(
            json.dumps(
                record_generation_event(
                    {
                        "type": "generation_started",
                        "id": job_id,
                        "client_request_id": job_payload.client_request_id,
                    }
                )
            )
        )

        async def emit(event: GenerationProgressEvent) -> None:
            await emit_generation_service_event(
                job_id=job_id,
                client_request_id=job_payload.client_request_id,
                event=event,
            )

        try:
            service = ImageGenService(config, output_dir=OUTPUT_DIR)
            with apply_config_overrides(config, job_payload.config_overrides):
                result = await service.generate(
                    job_payload.to_service_request(job_id),
                    callback=emit,
                )
            generation_job_store.complete_job(
                job_id,
                prompt=result.prompt,
                image_path=result.image_path,
                relative_image_path=result.relative_image_path,
                backend=result.backend,
                model_name=result.model_name,
                generation_time=result.generation_time,
                metadata=result.metadata,
            )
            return result
        except Exception as exc:
            error_msg = (
                "Insufficient memory to load the configured image backend."
                if isinstance(exc, MemoryError)
                else str(exc)
            )
            generation_job_store.fail_job(job_id, error_msg)
            await manager.broadcast(
                json.dumps(
                    record_generation_event(
                        {
                            "type": "generation_error",
                            "id": job_id,
                            "client_request_id": job_payload.client_request_id,
                            "error": error_msg,
                        }
                    )
                )
            )
            raise


async def run_generation_job_safely(job_id: str) -> None:
    """Background-task wrapper that records failures without crashing the server."""
    try:
        await run_generation_job(job_id)
    except Exception as exc:
        logger.error("Generation job %s failed: %s", job_id, exc)


def experiment_request_metadata(
    *,
    metadata: Dict[str, Any] | None = None,
    experiment_label: Optional[str] = None,
    prompt_family: Optional[str] = None,
    quality_flags: Optional[List[str]] = None,
    enable_plugins: Optional[bool] = None,
) -> Dict[str, Any]:
    """Merge operator experiment annotations into job metadata."""
    merged = dict(metadata or {})
    if experiment_label:
        merged["experiment_label"] = experiment_label
    if prompt_family:
        merged["prompt_family"] = prompt_family
    if quality_flags:
        merged["quality_flags"] = [str(flag).strip() for flag in quality_flags if str(flag).strip()]
    if enable_plugins is not None:
        merged["plugins_enabled_requested"] = enable_plugins
    return merged


def generation_job_from_request(
    *,
    prompt: Optional[str],
    meta_prompt: Optional[str],
    seed: Optional[int],
    publication_state: str,
    client_request_id: Optional[str],
    metadata: Dict[str, Any] | None = None,
    experiment_label: Optional[str] = None,
    prompt_family: Optional[str] = None,
    quality_flags: Optional[List[str]] = None,
    enable_plugins: Optional[bool] = None,
    recipe_id: Optional[str] = None,
    config_overrides: Dict[str, Any] | None = None,
) -> GenerationJobCreate:
    """Build a job creation payload, resolving a workflow recipe when requested."""
    merged_metadata = experiment_request_metadata(
        metadata=metadata,
        experiment_label=experiment_label,
        prompt_family=prompt_family,
        quality_flags=quality_flags,
        enable_plugins=enable_plugins,
    )
    if not recipe_id:
        return GenerationJobCreate(
            prompt=prompt,
            meta_prompt=meta_prompt,
            seed=seed,
            publication_state=publication_state,
            client_request_id=client_request_id,
            metadata=merged_metadata,
            config_overrides=dict(config_overrides or {}),
        )

    resolution = resolve_workflow_recipe(
        recipe_id,
        prompt=prompt,
        meta_prompt=meta_prompt,
        seed=seed,
        metadata=merged_metadata,
    )
    payload = resolution.to_job_payload(client_request_id=client_request_id)
    if config_overrides:
        payload["config_overrides"] = {
            **payload.get("config_overrides", {}),
            **config_overrides,
        }
    return GenerationJobCreate(**payload)


async def prefetch_default_fallback_model() -> None:
    """Fetch the default public fallback model in the background when needed."""
    if resolve_image_backend(config) != "small":
        return

    if is_model_cached(config.model.small_sd_model):
        return

    try:
        from huggingface_hub import snapshot_download

        logger.info("Prefetching small fallback model: %s", config.model.small_sd_model)
        await asyncio.to_thread(
            snapshot_download,
            repo_id=config.model.small_sd_model,
            token=configured_hf_token(),
        )
        logger.info("Small fallback model is ready")
    except Exception as e:
        logger.warning("Small fallback prefetch failed: %s", e)


@app.on_event("startup")
async def startup_event() -> None:
    generation_job_store.initialize()
    interrupted_jobs = generation_job_store.fail_interrupted_jobs(
        "Server restarted before this generation finished. Start a new run to retry it."
    )
    if interrupted_jobs:
        logger.warning(
            "Marked %s interrupted generation job(s) as failed during startup",
            len(interrupted_jobs),
        )
    asyncio.create_task(prefetch_default_fallback_model())


# API Endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "DreamGen API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "by": "Agentic Insights",
    }


@app.get("/api/status", response_model=SystemStatus)
async def get_status():
    """Get system status and configuration"""
    # Check if CUDA/MPS is available
    try:
        import torch

        gpu_available = torch.cuda.is_available() or torch.backends.mps.is_available()
    except Exception:
        gpu_available = False

    # Check Ollama availability
    try:
        import ollama

        ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434")).list()
        ollama_available = True
    except Exception:
        ollama_available = False

    runtime_status = runtime_manager.status()
    backend_name = runtime_status["active_backend_label"]

    return SystemStatus(
        status="ready",
        backend=backend_name,
        plugins_enabled=True,
        active_plugins=[name for name, info in plugin_manager.plugins.items() if info.enabled],
        gpu_available=gpu_available,
        ollama_available=ollama_available,
        configured_backend=runtime_status["configured_backend"],
        resolved_backend=runtime_status["resolved_backend"],
        active_backend_label=runtime_status["active_backend_label"],
        active_model=runtime_status["active_model"],
        active_model_id=runtime_status["active_model_id"],
        active_model_status=runtime_status["active_model_status"],
        preferred_backend=runtime_status["preferred_backend"],
        preferred_model=runtime_status["preferred_model"],
        preferred_model_id=runtime_status["preferred_model_id"],
        preferred_model_status=runtime_status["preferred_model_status"],
        fallback_backend=runtime_status["fallback_backend"],
        fallback_model=runtime_status["fallback_model"],
        fallback_model_id=runtime_status["fallback_model_id"],
        fallback_reason=runtime_status["fallback_reason"],
    )


@app.get("/api/plugins", response_model=List[PluginInfo])
async def get_plugins():
    """Get list of available plugins and their states"""
    return [
        PluginInfo(
            name=info.name,
            enabled=info.enabled,
            description=info.description,
            order=info.order,
            category=info.category,
            kind=info.kind,
            phase=info.phase,
        )
        for info in plugin_manager.registry_entries()
    ]


@app.get("/api/models/status")
async def get_model_status():
    """Get status of available models and their download progress"""
    return runtime_manager.status()


@app.get("/api/models/catalog")
async def get_image_engine_catalog():
    """Expose verified model identities separately from runtime readiness."""
    return image_engine_catalog()


@app.get("/api/models/recommended")
async def get_recommended_model_settings():
    """Recommend safe image settings from current cache and memory signals."""
    return runtime_manager.recommended()


@app.post("/api/models/unload")
async def unload_model_runtime():
    """Release process model caches and CUDA allocator state."""
    return runtime_manager.unload()


@app.post("/api/models/{model_id:path}/prefetch")
async def prefetch_model(model_id: str):
    """Prefetch alias for the existing asynchronous model download operation."""
    return await download_model(model_id)


async def _legacy_get_model_status():
    """Legacy implementation retained temporarily for download helpers."""
    # Use HF_HOME if set, otherwise use TRANSFORMERS_CACHE, fallback to default
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        hf_cache_dir = Path(hf_home) / "hub"
    else:
        transformers_cache = os.getenv("TRANSFORMERS_CACHE")
        if transformers_cache:
            hf_cache_dir = Path(transformers_cache) / "hub"
        else:
            hf_cache_dir = Path(
                os.getenv("HF_HUB_CACHE", os.path.expanduser("~/.cache/huggingface/hub"))
            )

    models = []
    model_configs = [
        {
            "id": "local:zimage",
            "name": "Z-Image-Turbo",
            "type": "text-to-image",
            "downloadable": True,
            "path": str(config.model.zimage_model_path),
        },
        {
            "id": config.model.smoke_test_model,
            "name": "Smoke Test SD",
            "type": "text-to-image",
            "downloadable": True,
        },
        {
            "id": config.model.small_sd_model,
            "name": "Small Stable Diffusion",
            "type": "text-to-image",
            "downloadable": True,
        },
        {
            "id": config.model.turbo_model,
            "name": "Turbo Stable Diffusion",
            "type": "text-to-image",
            "downloadable": True,
        },
        {
            "id": config.model.qwen_image_model,
            "name": "Qwen-Image",
            "type": "text-to-image",
            "downloadable": True,
        },
        {
            "id": config.model.ernie_image_model,
            "name": "ERNIE-Image",
            "type": "text-to-image",
            "downloadable": True,
        },
        {
            "id": "Qwen/Qwen-Image-Edit",
            "name": "Qwen-Image-Edit",
            "type": "image-to-image",
            "downloadable": True,
        },
        {
            "id": "black-forest-labs/FLUX.1-schnell",
            "name": "FLUX.1 Schnell",
            "type": "text-to-image",
            "downloadable": True,
        },
        {
            "id": "black-forest-labs/FLUX.1-dev",
            "name": "FLUX.1 Dev",
            "type": "text-to-image",
            "downloadable": True,
        },
    ]

    for model_config in model_configs:
        model_id = model_config["id"]
        downloadable = model_config.get("downloadable", True)

        if model_id == "local:zimage":
            model_path = Path(model_config["path"])
            status, size = inspect_local_zimage_model(model_path)
            models.append(
                {
                    "id": model_id,
                    "name": model_config["name"],
                    "type": model_config["type"],
                    "status": status,
                    "size": size,
                    "incomplete_files": 0,
                    "path": str(model_path),
                    "downloadable": True,
                }
            )
            continue

        if not downloadable:
            model_path = Path(model_config["path"])
            size = (
                sum(path.stat().st_size for path in model_path.rglob("*") if path.is_file())
                if model_path.exists()
                else 0
            )
            models.append(
                {
                    "id": model_id,
                    "name": model_config["name"],
                    "type": model_config["type"],
                    "status": "ready" if model_path.exists() else "not_downloaded",
                    "size": size,
                    "incomplete_files": 0,
                    "path": str(model_path),
                    "downloadable": False,
                }
            )
            continue

        model_path = hf_cache_dir / f"models--{model_id.replace('/', '--')}"

        status = "not_downloaded"
        size = 0
        incomplete_files = 0

        if model_path.exists():
            # Check for incomplete files
            blobs_path = model_path / "blobs"
            if blobs_path.exists():
                incomplete_files = len(list(blobs_path.glob("*.incomplete")))
                if incomplete_files > 0:
                    status = "downloading"
                else:
                    # Check if model has proper structure
                    snapshots_path = model_path / "snapshots"
                    if snapshots_path.exists() and list(snapshots_path.iterdir()):
                        status = "ready"
                    else:
                        status = "partial"

                # Calculate total size
                try:
                    total_size = sum(f.stat().st_size for f in blobs_path.iterdir() if f.is_file())
                    size = total_size
                except OSError:
                    size = 0

        models.append(
            {
                "id": model_id,
                "name": model_config["name"],
                "type": model_config["type"],
                "status": status,
                "size": size,
                "incomplete_files": incomplete_files,
                "path": str(model_path) if model_path.exists() else None,
                "downloadable": True,
            }
        )

    return {"models": models, "cache_dir": str(hf_cache_dir)}


@app.post("/api/models/{model_id:path}/download")
async def download_model(model_id: str):
    """Start downloading a model"""
    # URL decode the model_id
    from urllib.parse import unquote

    model_id = unquote(model_id)
    resolved_model_id = "Tongyi-MAI/Z-Image-Turbo" if model_id == "local:zimage" else model_id
    local_dir = str(config.model.zimage_model_path) if model_id == "local:zimage" else None

    try:
        from huggingface_hub import snapshot_download

        # Start download in background
        async def download_in_background():
            try:
                logger.info(f"Starting download for model: {resolved_model_id}")
                await manager.broadcast(
                    json.dumps(
                        {
                            "type": "model_download_started",
                            "model_id": model_id,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                )

                # Use snapshot_download to get the entire model
                loop = asyncio.get_event_loop()
                download_token = configured_hf_token()
                if resolved_model_id == config.model.mageflow_model:
                    from urllib import request as urllib_request

                    sidecar_request = urllib_request.Request(
                        f"{config.model.mageflow_url.rstrip('/')}/download",
                        data=b"",
                        method="POST",
                    )

                    def download_mageflow():
                        with urllib_request.urlopen(
                            sidecar_request,
                            timeout=config.model.mageflow_timeout_seconds,
                        ) as response:
                            return response.read()

                    await loop.run_in_executor(None, download_mageflow)
                elif local_dir is not None:
                    await loop.run_in_executor(
                        None,
                        lambda: snapshot_download(
                            repo_id=resolved_model_id,
                            local_dir=local_dir,
                            token=download_token,
                        ),
                    )
                else:
                    await loop.run_in_executor(
                        None,
                        lambda: snapshot_download(
                            repo_id=resolved_model_id,
                            token=download_token,
                        ),
                    )

                logger.info(f"Download completed for model: {resolved_model_id}")
                await manager.broadcast(
                    json.dumps(
                        {
                            "type": "model_download_completed",
                            "model_id": model_id,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                )

            except Exception as e:
                logger.error(f"Model download failed: {str(e)}")
                await manager.broadcast(
                    json.dumps(
                        {
                            "type": "model_download_error",
                            "model_id": model_id,
                            "error": str(e),
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                )

        # Start the download task
        asyncio.create_task(download_in_background())

        return {"message": f"Download started for {resolved_model_id}", "model_id": model_id}

    except Exception as e:
        logger.error(f"Failed to start download: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/hf-token")
async def set_hf_token(token_data: dict):
    """Set HuggingFace token"""
    token = token_data.get("token", "").strip()

    if not token or token == HF_TOKEN_PLACEHOLDER:
        raise HTTPException(status_code=400, detail="Token is required")

    try:
        # Save token to HF cache directory
        # Use configured HF_HOME or fallback
        hf_cache_dir = Path(os.getenv("HF_HOME", os.path.expanduser("~/.cache/huggingface")))
        hf_cache_dir.mkdir(parents=True, exist_ok=True)
        token_file = hf_cache_dir / "token"

        token_file.write_text(token, encoding="utf-8")
        try:
            token_file.chmod(0o600)
        except OSError:
            # Windows ACLs do not map cleanly to POSIX modes; keep the local
            # cache behavior working while avoiding a noisy failure.
            pass

        # Also set environment variable for current session
        os.environ["HF_TOKEN"] = token

        logger.info("HuggingFace token updated successfully")
        return {"message": "HuggingFace token updated successfully"}

    except Exception as e:
        logger.error(f"Failed to set HF token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/config/hf-token-status")
async def get_hf_token_status():
    """Check if HF token is configured"""
    # Check environment variable first
    if configured_hf_token():
        return {"configured": True, "source": "environment"}

    # Check token file using configured HF_HOME
    hf_cache_dir = Path(os.getenv("HF_HOME", os.path.expanduser("~/.cache/huggingface")))
    token_file = hf_cache_dir / "token"

    if token_file.exists():
        try:
            stored_token = token_file.read_text(encoding="utf-8").strip()
        except OSError:
            stored_token = ""
        if stored_token and stored_token != HF_TOKEN_PLACEHOLDER:
            return {"configured": True, "source": "file"}

    return {"configured": False, "source": None}


@app.post("/api/plugins/{plugin_name}/toggle")
async def toggle_plugin(plugin_name: str):
    """Toggle a plugin on/off"""
    if plugin_name not in plugin_manager.plugins and plugin_name not in plugin_manager.guards:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")

    current_state = plugin_manager.is_enabled(plugin_name)
    if current_state:
        plugin_manager.disable_plugin(plugin_name)
    else:
        plugin_manager.enable_plugin(plugin_name)

    return {"plugin": plugin_name, "enabled": not current_state}


@app.post("/api/plugins/order")
async def set_plugin_order(request: PluginOrderRequest):
    """Update plugin execution order."""
    existing_names = set(plugin_manager.plugins.keys())
    requested_names = set(request.ordered_names)

    if existing_names != requested_names:
        missing = sorted(existing_names - requested_names)
        extra = sorted(requested_names - existing_names)
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Ordered plugin list must contain every registered plugin exactly once",
                "missing": missing,
                "extra": extra,
            },
        )

    for index, name in enumerate(request.ordered_names, start=1):
        plugin_manager.set_plugin_order(name, index)

    return {"ordered_names": request.ordered_names}


@app.get("/api/ollama/models")
async def get_ollama_models():
    """Get list of available Ollama models"""
    try:
        models = list_ollama_models()
        current_prompt = resolve_prompt_model_from_models(
            models,
            reconcile_config=True,
            default_to_configured=False,
        )
        current_image = resolve_ollama_model(models, config.model.ollama_image_model, "image")
        try:
            version = get_ollama_version()
        except Exception:
            version = ""

        return {
            "models": [
                {
                    "name": model.name,
                    "size": model.size,
                    "modified": model.modified,
                    "digest": model.digest,
                    "format": model.format,
                    "family": model.family,
                    "capabilities": model.capabilities,
                    "can_prompt": model.can_prompt,
                    "can_vision": model.can_vision,
                    "can_image": model.can_image,
                }
                for model in models
            ],
            "current": current_prompt,
            "configured_prompt": config.model.ollama_model,
            "current_image": current_image,
            "configured_image": config.model.ollama_image_model,
            "host": ollama_host(),
            "version": version,
        }
    except Exception as e:
        logger.error(f"Failed to get Ollama models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get Ollama models: {str(e)}")


@app.post("/api/ollama/model")
async def set_ollama_model(data: dict):
    """Set the active Ollama model"""
    model_name = data.get("model")

    if not model_name:
        raise HTTPException(status_code=400, detail="Model name is required")

    try:
        set_configured_prompt_model(model_name)

        logger.info(f"Ollama model set to: {model_name}")
        return {"message": f"Ollama model set to {model_name}", "model": model_name}
    except Exception as e:
        logger.error(f"Failed to set Ollama model: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to set Ollama model: {str(e)}")


@app.get("/api/config/generation")
async def get_generation_config():
    """Get current generation configuration parameters"""
    return generation_config_payload()


@app.post("/api/config/generation")
async def set_generation_config(data: dict):
    """Update generation configuration parameters"""
    try:
        if "width" in data:
            config.image.width = int(data["width"])
        if "height" in data:
            config.image.height = int(data["height"])
        if "num_inference_steps" in data:
            config.image.num_inference_steps = int(data["num_inference_steps"])
        if "guidance_scale" in data:
            config.image.guidance_scale = float(data["guidance_scale"])
        if "true_cfg_scale" in data:
            config.image.true_cfg_scale = float(data["true_cfg_scale"])
        if "ollama_temperature" in data:
            config.model.ollama_temperature = float(data["ollama_temperature"])
        if "ollama_model" in data:
            prompt_model = str(data["ollama_model"]).strip()
            if not prompt_model:
                raise ValueError("ollama_model must not be empty")
            set_configured_prompt_model(prompt_model)
        if "image_backend" in data:
            backend = str(data["image_backend"]).lower()
            if backend not in ALLOWED_IMAGE_BACKENDS:
                raise ValueError(
                    f"Invalid image backend: {backend} "
                    f"(must be one of {', '.join(sorted(ALLOWED_IMAGE_BACKENDS))})"
                )
            config.model.image_backend = backend
        if "ollama_image_model" in data:
            config.model.ollama_image_model = str(data["ollama_image_model"]).strip()
        if "mageflow_model" in data:
            config.model.mageflow_model = (
                str(data["mageflow_model"]).strip() or "microsoft/Mage-Flow"
            )
        if "mageflow_steps" in data:
            config.model.mageflow_steps = int(data["mageflow_steps"])
        if "mageflow_cfg" in data:
            config.model.mageflow_cfg = float(data["mageflow_cfg"])
        if "qwen_image_model" in data:
            config.model.qwen_image_model = (
                str(data["qwen_image_model"]).strip() or "diffusers/qwen-image-nf4"
            )
        if "qwen_prompt_magic" in data:
            config.model.qwen_prompt_magic = parse_bool_config(data["qwen_prompt_magic"])
        if "qwen_device_map" in data:
            config.model.qwen_device_map = str(data["qwen_device_map"]).strip() or "balanced"
        if "qwen_lightning" in data:
            config.model.qwen_lightning = parse_bool_config(data["qwen_lightning"])
        if "ernie_image_model" in data:
            config.model.ernie_image_model = (
                str(data["ernie_image_model"]).strip() or "baidu/ERNIE-Image-Turbo"
            )
        if "ernie_prompt_enhancer" in data:
            config.model.ernie_prompt_enhancer = parse_bool_config(data["ernie_prompt_enhancer"])
        if "enabled_loras" in data:
            enabled_loras = data["enabled_loras"]
            if not isinstance(enabled_loras, list):
                raise ValueError("enabled_loras must be a list of names")
            config.model.lora.enabled_loras = [
                str(lora_name).strip() for lora_name in enabled_loras if str(lora_name).strip()
            ]
        if "lora_application_probability" in data:
            probability = float(data["lora_application_probability"])
            if not 0.0 <= probability <= 1.0:
                raise ValueError("lora_application_probability must be between 0.0 and 1.0")
            config.model.lora.application_probability = probability
        if "entropy_level" in data:
            entropy_level = str(data["entropy_level"]).strip().lower()
            if entropy_level not in {"calm", "strange", "wild"}:
                raise ValueError("entropy_level must be calm, strange, or wild")
            config.plugins.entropy_level = entropy_level

        runtime_manager.persist_selection()

        logger.info(f"Generation config updated: {data}")
        return {
            "message": "Configuration updated successfully",
            "config": generation_config_payload(),
        }
    except Exception as e:
        logger.error(f"Failed to update generation config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update configuration: {str(e)}")


@app.get("/api/recipes")
async def get_workflow_recipes():
    """List built-in workflow recipes."""
    return {"recipes": [recipe.summary() for recipe in list_workflow_recipes()]}


@app.get("/api/recipes/{recipe_id}")
async def get_workflow_recipe_detail(recipe_id: str):
    """Return a built-in workflow recipe definition."""
    try:
        return get_workflow_recipe(recipe_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/recipes/{recipe_id}/resolve")
async def resolve_workflow_recipe_endpoint(recipe_id: str, request: RecipeResolveRequest):
    """Resolve a workflow recipe into a generation job payload."""
    try:
        resolution = resolve_workflow_recipe(
            recipe_id,
            prompt=request.prompt,
            meta_prompt=request.meta_prompt,
            seed=request.seed,
            metadata=request.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "recipe": resolution.recipe.to_dict(),
        "job_request": resolution.to_job_payload(client_request_id=request.client_request_id),
    }


@app.post("/api/prompt", response_model=PromptResponse)
async def generate_prompt(request: PromptRequest):
    """Generate a prompt without creating an image."""
    prompt_id = str(uuid.uuid4())
    try:
        await broadcast_task_progress(
            task="prompt_generation",
            task_id=prompt_id,
            client_request_id=request.client_request_id,
            progress=15,
            label="Preparing prompt generation",
            detail="Collecting your meta prompt and warming up the prompt model.",
        )
        prompt_gen = PromptGenerator(config)
        await broadcast_task_progress(
            task="prompt_generation",
            task_id=prompt_id,
            client_request_id=request.client_request_id,
            progress=60,
            label="Generating prompt",
            detail="Asking Ollama to turn the meta prompt into a final image prompt.",
        )
        prompt = await prompt_gen.generate_prompt(meta_prompt=request.meta_prompt)
        await broadcast_task_progress(
            task="prompt_generation",
            task_id=prompt_id,
            client_request_id=request.client_request_id,
            progress=100,
            label="Prompt ready",
            detail="The generated prompt is ready to edit or use directly.",
        )
        return PromptResponse(prompt=prompt)
    except Exception as e:
        logger.error(f"Prompt generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_image(request: GenerateRequest):
    """Generate a single image"""
    try:
        job = generation_job_store.create_job(
            generation_job_from_request(
                prompt=request.prompt,
                meta_prompt=request.meta_prompt,
                seed=request.seed,
                publication_state="draft",
                client_request_id=request.client_request_id,
                experiment_label=request.experiment_label,
                prompt_family=request.prompt_family,
                quality_flags=request.quality_flags,
                enable_plugins=request.enable_plugins,
                recipe_id=request.recipe_id,
                config_overrides=request.config_overrides,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    generation_id = job["id"]
    try:
        result = await run_generation_job(generation_id)
        if result is None:
            raise RuntimeError(f"Generation job {generation_id} did not produce a result")

        return GenerateResponse(
            id=generation_id,
            prompt=result.prompt,
            image_path=result.relative_image_path,
            metadata=result.metadata,
            created_at=result.created_at,
        )

    except MemoryError as e:
        error_msg = "Insufficient memory to load the configured image backend."
        logger.error(f"Memory error loading image backend: {str(e)}")
        raise HTTPException(status_code=507, detail=error_msg)
    except Exception as e:
        logger.error(f"Generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs")
async def create_generation_job(request: JobCreateRequest, background_tasks: BackgroundTasks):
    """Create a durable generation job and schedule it on the local worker."""
    try:
        job = generation_job_store.create_job(
            generation_job_from_request(
                prompt=request.prompt,
                meta_prompt=request.meta_prompt,
                seed=request.seed,
                publication_state=request.publication_state,
                client_request_id=request.client_request_id,
                metadata=request.metadata,
                experiment_label=request.experiment_label,
                prompt_family=request.prompt_family,
                quality_flags=request.quality_flags,
                recipe_id=request.recipe_id,
                config_overrides=request.config_overrides,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(run_generation_job_safely, job["id"])
    return job


@app.get("/api/jobs")
async def list_generation_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List recent durable generation jobs."""
    return {
        "jobs": generation_job_store.list_jobs(status=status, limit=limit, offset=offset),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/jobs/{job_id}")
async def get_generation_job(job_id: str):
    """Return one durable generation job with its progress events."""
    job = generation_job_store.get_job(job_id, include_events=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Generation job not found")
    return job


@app.get("/api/jobs/{job_id}/events")
async def get_generation_job_events(job_id: str):
    """Return persisted lifecycle events for one generation job."""
    if generation_job_store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Generation job not found")
    return {"events": generation_job_store.get_events(job_id)}


@app.get("/api/generation/events")
async def get_generation_events(limit: int = Query(25, ge=1, le=100)):
    """Return recent generation lifecycle events for operator dashboards."""
    events = list(recent_generation_events)[:limit]
    if not events:
        events = read_lifecycle_events(OUTPUT_DIR / "metrics", limit)
    return {"events": events, "total": len(recent_generation_events), "limit": limit}


@app.get("/api/generation/metrics")
async def get_generation_metrics(limit: int = Query(500, ge=1, le=2000)):
    """Return aggregated phase timing and outcome metrics for operator diagnostics."""
    events = read_lifecycle_events(OUTPUT_DIR / "metrics", limit)
    completed = [
        event
        for event in events
        if event.get("name") == "generation_completed" and isinstance(event.get("payload"), dict)
    ]
    phase_totals: Dict[str, Dict[str, float]] = {}
    for event in completed:
        payload = event["payload"]
        key = f"{payload.get('backend', 'unknown')}::{payload.get('model', 'unknown')}"
        bucket = phase_totals.setdefault(key, {"runs": 0.0})
        bucket["runs"] += 1
        for phase, duration in (payload.get("phase_durations_ms") or {}).items():
            bucket[phase] = bucket.get(phase, 0.0) + float(duration or 0)

    for bucket in phase_totals.values():
        runs = max(bucket["runs"], 1)
        for key in list(bucket):
            if key not in {"runs"}:
                bucket[key] = round(bucket[key] / runs, 2)

    return {
        "events": len(events),
        "completed_generations": len(completed),
        "phase_averages_ms": phase_totals,
        "otel_enabled": os.getenv("DREAMGEN_OTEL_ENABLED", "0").lower() in {"1", "true", "yes"},
        "jsonl_path": str(
            (OUTPUT_DIR / "metrics" / "generation_events.jsonl").relative_to(OUTPUT_DIR)
        ),
    }


@app.get("/api/gallery")
async def get_gallery(limit: int = 50, offset: int = 0):
    """Get list of generated images without blocking on every prompt file in storage."""
    indexed_images = await asyncio.to_thread(build_gallery_index, OUTPUT_DIR)
    paginated_images = await hydrate_gallery_entries(indexed_images[offset : offset + limit])
    return {
        "images": paginated_images,
        "total": len(indexed_images),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/gallery/catalog")
async def get_gallery_catalog(
    publication_state: Optional[str] = Query(None, alias="state"),
    backend: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    prompt_family: Optional[str] = Query(None),
    quality_flag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = 100,
    offset: int = 0,
):
    """List backend catalog entries for operator publication review."""
    if not catalog_path_for(OUTPUT_DIR).exists():
        await asyncio.to_thread(
            backfill_catalog, OUTPUT_DIR, default_state="published", include_placeholders=True
        )

    catalog = await asyncio.to_thread(load_catalog, OUTPUT_DIR)
    entries = sorted(
        catalog["assets"].values(),
        key=lambda entry: str(entry.get("created_at", "")),
        reverse=True,
    )
    if publication_state:
        normalized_state = publication_state.strip().lower()
        entries = [entry for entry in entries if entry.get("publication_state") == normalized_state]
    entries = [
        entry
        for entry in entries
        if matches_gallery_filters(
            entry,
            backend=backend,
            model=model,
            prompt_family=prompt_family,
            quality_flag=quality_flag,
            search=search,
        )
    ]

    page_entries = []
    for entry in entries[offset : offset + limit]:
        payload = dict(entry)
        payload["metadata"] = display_metadata_for_catalog(entry.get("metadata", {}))
        image_file = OUTPUT_DIR / str(entry.get("path", ""))
        if image_file.exists():
            payload["size"] = image_file.stat().st_size
            payload["image_url"] = f"/images/{image_file.relative_to(OUTPUT_DIR).as_posix()}"
        page_entries.append(payload)

    return {
        "assets": page_entries,
        "total": len(entries),
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/gallery/facets")
async def get_gallery_facets():
    """Return distinct experiment/catalog filters for local review workflows."""
    if not catalog_path_for(OUTPUT_DIR).exists():
        await asyncio.to_thread(
            backfill_catalog, OUTPUT_DIR, default_state="published", include_placeholders=True
        )

    catalog = await asyncio.to_thread(load_catalog, OUTPUT_DIR)
    entries = list(catalog["assets"].values())
    return gallery_experiment_facets(entries)


@app.get("/api/gallery/sync/status")
async def get_gallery_sync_status(
    bucket: str = DEFAULT_BUCKET,
    since: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1, le=500),
    include_featured: bool = True,
):
    """Return the local catalog-driven R2 publish plan status."""
    try:
        return await asyncio.to_thread(
            build_publish_status,
            OUTPUT_DIR,
            bucket=bucket,
            since=since,
            limit=limit,
            include_featured=include_featured,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/gallery/catalog/backfill")
async def backfill_gallery_catalog(default_state: str = "published"):
    """Backfill existing local output images into the backend publication catalog."""
    try:
        result = await asyncio.to_thread(
            backfill_catalog,
            OUTPUT_DIR,
            default_state=default_state,
            include_placeholders=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.patch("/api/gallery/publication/{image_path:path}")
async def update_image_publication(image_path: str, request: PublicationUpdateRequest):
    """Update publication state for a generated image."""
    key = normalize_gallery_key(image_path)
    full_path = (OUTPUT_DIR / key).resolve()
    output_root = OUTPUT_DIR.resolve()

    if not full_path.is_relative_to(output_root):
        raise HTTPException(status_code=400, detail="Invalid image path")

    try:
        entry = await asyncio.to_thread(
            set_publication_state,
            OUTPUT_DIR,
            key,
            request.state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Catalog entry not found") from exc

    return entry


@app.post("/api/gallery/publication/bulk")
async def bulk_update_image_publication(request: BulkPublicationRequest):
    """Apply one publication state to a selected set of catalog entries."""
    updated: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for image_path in request.image_paths:
        key = normalize_gallery_key(image_path)
        full_path = (OUTPUT_DIR / key).resolve()
        if not full_path.is_relative_to(OUTPUT_DIR.resolve()):
            failures.append({"path": key, "error": "Invalid image path"})
            continue
        try:
            updated.append(
                await asyncio.to_thread(set_publication_state, OUTPUT_DIR, key, request.state)
            )
        except (ValueError, PermissionError, FileNotFoundError, KeyError) as exc:
            failures.append({"path": key, "error": str(exc)})
    if not updated and failures:
        raise HTTPException(status_code=409, detail={"updated": [], "failures": failures})
    return {"updated": updated, "failures": failures, "state": request.state}


@app.delete("/api/gallery/{image_path:path}")
async def delete_image(image_path: str):
    """Delete an image from the gallery"""
    key = normalize_gallery_key(image_path)
    full_path = (OUTPUT_DIR / key).resolve()
    output_root = OUTPUT_DIR.resolve()

    if not full_path.is_relative_to(output_root):
        raise HTTPException(status_code=400, detail="Invalid image path")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    # Delete image and sidecar files
    full_path.unlink()
    prompt_path = full_path.with_suffix(".txt")
    if prompt_path.exists():
        prompt_path.unlink()
    metadata_path = metadata_path_for(full_path)
    if metadata_path.exists():
        metadata_path.unlink()
    remove_image(OUTPUT_DIR, key)

    return {"message": "Image deleted successfully"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Echo back or handle commands
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/batch")
async def batch_generate(count: int = 5, delay: int = 0):
    """Generate multiple images in batch"""
    batch_id = str(uuid.uuid4())
    results = []

    for i in range(count):
        if delay > 0 and i > 0:
            await asyncio.sleep(delay)

        try:
            # Generate each image
            request = GenerateRequest()
            result = await generate_image(request)
            results.append(result.dict())
        except Exception as e:
            logger.error(f"Batch generation {i+1}/{count} failed: {str(e)}")
            results.append({"error": str(e)})

    return {"batch_id": batch_id, "count": count, "results": results}


@app.get("/api/edit/capabilities")
async def get_edit_capabilities():
    """Return official controls plus live checkpoint/GPU readiness."""
    return await asyncio.to_thread(edit_capabilities_with_runtime)


@app.get("/api/edit/jobs")
async def list_edit_jobs(root_job_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500)):
    """List recoverable edit history, optionally scoped to one lineage root."""
    return {"jobs": edit_job_store.list_jobs(root_job_id=root_job_id, limit=limit)}


@app.post("/api/edit/models/{variant}/download")
async def download_mage_edit_model(variant: str):
    try:
        descriptor = get_variant(variant)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not descriptor.get("available"):
        raise HTTPException(
            status_code=503,
            detail="Enable the exact pinned Comfy-Org mirror revision before download.",
        )
    try:
        return await asyncio.to_thread(download_edit_model, variant)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/edit/jobs", status_code=202)
async def create_mage_edit_job(
    background_tasks: BackgroundTasks,
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    command: str = Form(...),
    variant: str = Form("turbo"),
    seed: int = Form(42),
    steps: Optional[int] = Form(None),
    guidance: Optional[float] = Form(None),
    max_size: int = Form(1024),
    negative_prompt: str = Form(""),
    vl_cond_long_edge: int = Form(384),
    source_path: Optional[str] = Form(None),
    parent_job_id: Optional[str] = Form(None),
):
    """Queue Mage-Flow-Edit through the explicitly authorized pinned mirror."""
    command = command.strip()
    if not command:
        raise HTTPException(status_code=422, detail="Edit command is required")
    try:
        descriptor = get_variant(variant)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    live = edit_capabilities_with_runtime()
    live_variant = next(item for item in live["variants"] if item["id"] == variant)
    if not live_variant.get("ready"):
        raise HTTPException(
            status_code=503,
            detail={
                "message": "The pinned Mage-Flow-Edit mirror checkpoint is not ready.",
                "repository": descriptor["repository"],
                "reason": live_variant.get("availability_reason") or live.get("runtime_reason"),
                "action": "Download the pinned Comfy-Org mirror artifacts for this variant.",
            },
        )
    resolved_steps = steps if steps is not None else int(descriptor["default_steps"])
    resolved_guidance = guidance if guidance is not None else float(descriptor["default_guidance"])
    if not 1 <= resolved_steps <= 50 or not 1.0 <= resolved_guidance <= 10.0:
        raise HTTPException(status_code=422, detail="Unsupported steps or guidance value")
    if max_size not in {512, 768, 1024, 1536, 2048}:
        raise HTTPException(
            status_code=422, detail="max_size must be 512, 768, 1024, 1536, or 2048"
        )
    if not 0 <= seed <= 2**31 - 1:
        raise HTTPException(status_code=422, detail="seed must be between 0 and 2147483647")

    references = list(files or [])
    if file is not None:
        references.insert(0, file)
    if not 1 <= len(references) <= 3:
        raise HTTPException(
            status_code=422,
            detail="Mage-Flow-Edit supports between one and three reference images",
        )
    source_payloads = [
        (await reference.read(), reference.filename or f"reference-{index + 1}.png")
        for index, reference in enumerate(references)
    ]
    try:
        for content, _filename in source_payloads:
            with Image.open(io.BytesIO(content)) as candidate:
                candidate.verify()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid source image: {exc}") from exc

    parent = edit_job_store.get_job(parent_job_id) if parent_job_id else None
    if parent_job_id and (not parent or parent.get("status") != "succeeded"):
        raise HTTPException(status_code=422, detail="parent_job_id must reference a succeeded edit")
    job_id = str(uuid.uuid4())
    root_id = str(parent["root_job_id"]) if parent else job_id
    version = max((job["version"] for job in edit_job_store.list_jobs(root_id)), default=0) + 1
    source_artifacts = []
    for index, (content, filename) in enumerate(source_payloads):
        source_file, source_sha = persist_source(OUTPUT_DIR, root_id, content)
        source_artifacts.append(
            {
                "index": index,
                "role": "primary" if index == 0 else "reference",
                "path": f"/images/{source_file.relative_to(OUTPUT_DIR).as_posix()}",
                "sha256": source_sha,
                "original_filename": filename,
                "catalog_path": source_path if index == 0 else None,
            }
        )
    source_url = str(source_artifacts[0]["path"])
    source_sha = str(source_artifacts[0]["sha256"])
    settings = {
        "command": command,
        "variant": variant,
        "seed": seed,
        "steps": resolved_steps,
        "guidance": resolved_guidance,
        "max_size": max_size,
        "negative_prompt": negative_prompt,
        "vl_cond_long_edge": vl_cond_long_edge,
    }
    metadata = {
        "operation": "mage-flow-edit",
        "source_catalog_path": source_path,
        "source_sha256": source_sha,
        "source_sha256s": [artifact["sha256"] for artifact in source_artifacts],
        "source_artifacts": source_artifacts,
        "settings": settings,
        "model": descriptor["artifact_repository"],
        "upstream_model": descriptor["upstream_repository"],
        "model_revision": descriptor["verified_revision"],
        "artifact_path": descriptor["artifact_path"],
        "artifact_sha256": descriptor["artifact_sha256"],
        "provenance_status": live["provenance_status"],
        "configuration_repository": live["configuration_source"]["repository"],
        "configuration_revision": live["configuration_source"]["revision"],
        "source_revision": live["source_revision"],
        "edit_lineage": {
            "role": "source",
            "root_job_id": root_id,
            "parent_job_id": parent_job_id,
            "version": version,
            "decision_state": "pending",
        },
        "hardware_at_queue": live.get("gpu"),
    }
    source_manifest_path, source_manifest_sha = append_manifest(
        OUTPUT_DIR,
        root_id,
        job_id,
        version,
        {
            "event": "source_registered",
            "job_id": job_id,
            "root_job_id": root_id,
            "parent_job_id": parent_job_id,
            "source_sha256": source_sha,
            "source_sha256s": [artifact["sha256"] for artifact in source_artifacts],
            "source_artifacts": source_artifacts,
            "source_path": source_url,
            "command": command,
            "model": descriptor["artifact_repository"],
            "upstream_model": descriptor["upstream_repository"],
            "model_revision": descriptor["verified_revision"],
            "artifact_path": descriptor["artifact_path"],
            "artifact_sha256": descriptor["artifact_sha256"],
            "provenance_status": live["provenance_status"],
            "configuration_repository": live["configuration_source"]["repository"],
            "configuration_revision": live["configuration_source"]["revision"],
            "source_revision": live["source_revision"],
            "settings": settings,
            "hardware": live.get("gpu"),
            "decision_state": "pending",
        },
    )
    metadata["source_manifest_path"] = str(source_manifest_path)
    metadata["source_manifest_sha256"] = source_manifest_sha
    for artifact in source_artifacts:
        artifact_path = OUTPUT_DIR / str(artifact["path"]).removeprefix("/images/")
        register_image(
            artifact_path,
            OUTPUT_DIR,
            prompt=f"SOURCE {int(artifact['index']) + 1} for: {command}",
            metadata={
                **metadata,
                "source_index": artifact["index"],
                "edit_lineage": {
                    **metadata["edit_lineage"],
                    "source_index": artifact["index"],
                },
            },
            publication_state="draft",
        )
    job = edit_job_store.create_job(
        job_id=job_id,
        prompt=command,
        strength=0.0,
        backend="mage-flow-edit",
        source_path=source_url,
        source_filename=str(source_artifacts[0]["original_filename"]),
        metadata=metadata,
        root_job_id=root_id,
        parent_job_id=parent_job_id,
        version=version,
    )
    background_tasks.add_task(execute_mage_edit_job, job_id, source_payloads)
    return job


@app.post("/api/edit/jobs/{job_id}/retry", status_code=202)
async def retry_mage_edit_job(job_id: str, background_tasks: BackgroundTasks):
    """Replay one recovered edit with its exact immutable sources and settings."""
    job = edit_job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Edit job not found")
    if job.get("status") != "succeeded" or job.get("backend") != "mage-flow-edit":
        raise HTTPException(status_code=409, detail="Only succeeded Mage-Flow-Edit jobs can retry")
    metadata = dict(job.get("metadata") or {})
    settings = metadata.get("settings")
    artifacts = metadata.get("source_artifacts")
    if not isinstance(settings, dict) or not isinstance(artifacts, list) or not artifacts:
        raise HTTPException(status_code=409, detail="Recovered job is missing immutable retry data")
    uploads: list[UploadFile] = []
    output_root = OUTPUT_DIR.resolve()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise HTTPException(status_code=409, detail="Recovered source metadata is invalid")
        relative = str(artifact.get("path") or "").removeprefix("/images/")
        source_file = (OUTPUT_DIR / relative).resolve()
        if not source_file.is_relative_to(output_root) or not source_file.is_file():
            raise HTTPException(status_code=409, detail="Recovered source file is unavailable")
        source_bytes = source_file.read_bytes()
        expected_sha = str(artifact.get("sha256") or "")
        if not expected_sha or sha256_bytes(source_bytes) != expected_sha:
            raise HTTPException(
                status_code=409,
                detail="Recovered source file no longer matches its immutable SHA-256",
            )
        uploads.append(
            UploadFile(
                file=io.BytesIO(source_bytes),
                filename=str(artifact.get("original_filename") or f"reference-{index + 1}.png"),
            )
        )
    required = {
        "command",
        "variant",
        "seed",
        "steps",
        "guidance",
        "max_size",
        "negative_prompt",
        "vl_cond_long_edge",
    }
    if not required.issubset(settings):
        raise HTTPException(status_code=409, detail="Recovered settings are incomplete")
    return await create_mage_edit_job(
        background_tasks,
        files=uploads,
        file=None,
        command=str(settings["command"]),
        variant=str(settings["variant"]),
        seed=int(settings["seed"]),
        steps=int(settings["steps"]),
        guidance=float(settings["guidance"]),
        max_size=int(settings["max_size"]),
        negative_prompt=str(settings["negative_prompt"]),
        vl_cond_long_edge=int(settings["vl_cond_long_edge"]),
        source_path=metadata.get("source_catalog_path"),
        parent_job_id=job_id,
    )


@app.post("/api/edit/jobs/{job_id}/cancel")
async def cancel_edit_job(job_id: str):
    job = edit_job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Edit job not found")
    return edit_job_store.cancel_job(job_id)


@app.post("/api/edit/jobs/{job_id}/decision")
async def decide_edit_job(job_id: str, request: EditDecisionRequest):
    job = edit_job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Edit job not found")
    if job.get("status") != "succeeded" or not job.get("edited_path"):
        raise HTTPException(status_code=409, detail="Only succeeded derivatives can be decided")
    edit_lineage = job.get("metadata", {}).get("edit_lineage", {})
    if edit_lineage.get("diagnostic_fixture"):
        raise HTTPException(
            status_code=409,
            detail="Diagnostic fixtures cannot be approved or rejected",
        )
    key = str(job["edited_path"]).removeprefix("/images/")
    manifest_path, manifest_sha = append_manifest(
        OUTPUT_DIR,
        str(job["root_job_id"]),
        job_id,
        int(job["version"]),
        {
            "event": "decision",
            "job_id": job_id,
            "root_job_id": job["root_job_id"],
            "parent_job_id": job.get("parent_job_id"),
            "decision_state": request.decision,
            "derivative_sha256": job.get("metadata", {}).get("derivative_sha256"),
        },
    )
    try:
        catalog_entry = set_edit_decision(
            OUTPUT_DIR,
            key,
            request.decision,
            decision_manifest_path=manifest_path.relative_to(OUTPUT_DIR).as_posix(),
            decision_manifest_sha256=manifest_sha,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = edit_job_store.set_decision(
        job_id, request.decision, manifest_path=str(manifest_path)
    )
    return {**updated, "catalog": catalog_entry}


@app.post("/api/edit", response_model=EditResponse)
async def edit_image(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    strength: float = Form(0.8),
    backend: str = Form("auto"),
    source_path: Optional[str] = Form(None),
):
    """Run an image edit and persist source/output lineage as a durable edit job."""
    if not 0.0 <= strength <= 1.0:
        raise HTTPException(status_code=422, detail="strength must be between 0 and 1")
    requested_backend = backend.strip().lower() or "auto"
    if requested_backend not in {"auto", "mock", "qwen"}:
        raise HTTPException(status_code=400, detail="backend must be auto, mock, or qwen")
    resolved_backend = "mock" if requested_backend == "mock" else "qwen-image-edit"
    image_bytes = await file.read()
    edit_job = edit_job_store.create_job(
        prompt=prompt,
        strength=strength,
        backend=resolved_backend,
        source_path=source_path,
        source_filename=file.filename,
        metadata={"operation": "edit", "source_path": source_path},
    )
    edit_id = edit_job["id"]
    edit_job_store.start_job(edit_id)
    started = datetime.now().isoformat()
    await manager.broadcast(
        json.dumps({"type": "edit_started", "id": edit_id, "timestamp": started})
    )
    record_generation_event(
        {
            "type": "edit_lifecycle",
            "name": "edit_started",
            "id": edit_id,
            "backend": resolved_backend,
        }
    )

    try:
        import io

        original_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if resolved_backend == "mock":
            digest = hashlib.sha256(prompt.encode("utf-8")).digest()
            tint = (digest[0], digest[1], digest[2])
            overlay = Image.new("RGB", original_img.size, tint)
            edited_image = Image.blend(original_img, overlay, 0.12 + (strength * 0.2))
        else:
            from src.generators.image_editor import ImageEditor

            editor = ImageEditor(config)
            edited_image = await editor.edit_image(image_bytes, prompt, strength)

        lineage = {
            "operation": "edit",
            "edit_job_id": edit_id,
            "source_path": source_path,
            "source_filename": file.filename,
            "backend": resolved_backend,
            "strength": strength,
        }
        original_path = save_image_and_prompt(original_img, f"ORIGINAL: {prompt}", str(OUTPUT_DIR))
        edited_path = save_image_and_prompt(edited_image, f"EDITED: {prompt}", str(OUTPUT_DIR))
        register_image(
            original_path,
            OUTPUT_DIR,
            prompt=f"ORIGINAL: {prompt}",
            metadata={
                **lineage,
                "role": "source",
                "edit_lineage": {
                    "role": "source",
                    "root_job_id": edit_id,
                    "version": 1,
                    "decision_state": "pending",
                    "diagnostic_fixture": resolved_backend == "mock",
                },
            },
            publication_state="draft",
        )
        result_lineage = {
            "role": "derivative",
            "root_job_id": edit_id,
            "version": 1,
            "decision_state": "pending",
            "diagnostic_fixture": resolved_backend == "mock",
        }
        register_image(
            edited_path,
            OUTPUT_DIR,
            prompt=f"EDITED: {prompt}",
            metadata={**lineage, "role": "result", "edit_lineage": result_lineage},
            publication_state="draft",
        )

        original_relative = f"/images/{original_path.relative_to(OUTPUT_DIR).as_posix()}"
        edited_relative = f"/images/{edited_path.relative_to(OUTPUT_DIR).as_posix()}"
        completed_metadata = {
            **lineage,
            "model": resolved_backend,
            "edit_lineage": result_lineage,
        }
        edit_job_store.complete_job(
            edit_id,
            original_path=original_relative,
            edited_path=edited_relative,
            metadata=completed_metadata,
        )
        await manager.broadcast(
            json.dumps(
                {
                    "type": "edit_completed",
                    "id": edit_id,
                    "original_path": original_relative,
                    "edited_path": edited_relative,
                    "prompt": prompt,
                }
            )
        )
        record_generation_event(
            {
                "type": "edit_lifecycle",
                "name": "edit_completed",
                "id": edit_id,
                "backend": resolved_backend,
                "payload": completed_metadata,
            }
        )
        return EditResponse(
            id=edit_id,
            prompt=prompt,
            original_path=original_relative,
            edited_path=edited_relative,
            metadata={**completed_metadata, "job_id": edit_id},
            created_at=datetime.now().isoformat(),
        )
    except Exception as exc:
        logger.error("Image edit failed: %s", exc)
        edit_job_store.fail_job(edit_id, str(exc))
        record_generation_event(
            {"type": "edit_lifecycle", "name": "edit_failed", "id": edit_id, "error": str(exc)}
        )
        await manager.broadcast(
            json.dumps({"type": "edit_error", "id": edit_id, "error": str(exc)})
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/edit/jobs/{job_id}")
async def get_edit_job(job_id: str):
    """Return persisted edit state and source/output lineage."""
    job = edit_job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Edit job not found")
    return job


if __name__ == "__main__":
    import uvicorn

    # Run the server
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
