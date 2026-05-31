"""
FastAPI server for Continuous Image Generation
Provides REST API and WebSocket endpoints for the Next.js frontend
"""

import asyncio
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

from src.generators.factory import backend_label, is_model_cached, resolve_image_backend
from src.generators.prompt_generator import PromptGenerator
from src.plugins import plugin_manager, register_lora_plugin
from src.plugins.lora import get_available_loras
from src.services import (
    GenerationJobCreate,
    GenerationProgressEvent,
    ImageGenService,
    SQLiteGenerationJobStore,
)
from src.utils.config import Config
from src.utils.gallery_publisher import DEFAULT_BUCKET, build_publish_status
from src.utils.ollama import (
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
    set_publication_state,
)
from src.utils.storage import StorageManager, metadata_path_for, save_image_and_prompt

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_IMAGE_BACKENDS = {
    "auto",
    "flux",
    "ollama",
    "zimage",
    "qwen",
    "small",
    "turbo",
    "smoke",
    "mock",
}
MAX_RECENT_GENERATION_EVENTS = 100

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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
config = Config()
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
    if not model_path.exists():
        return ("not_downloaded", 0)

    size = sum(path.stat().st_size for path in model_path.rglob("*") if path.is_file())
    transformer_files = list((model_path / "transformer").glob("*.safetensors"))
    text_encoder_files = list((model_path / "text_encoder").glob("*.safetensors"))
    required_files = [
        model_path / "model_index.json",
        model_path / "tokenizer" / "tokenizer.json",
        model_path / "vae" / "diffusion_pytorch_model.safetensors",
    ]

    if transformer_files and text_encoder_files and all(path.exists() for path in required_files):
        return ("ready", size)

    return ("partial", size)


def generation_config_payload() -> Dict[str, Any]:
    """Serialize mutable generation/runtime settings for the frontend."""
    return {
        "width": config.image.width,
        "height": config.image.height,
        "num_inference_steps": config.image.num_inference_steps,
        "guidance_scale": config.image.guidance_scale,
        "true_cfg_scale": config.image.true_cfg_scale,
        "ollama_temperature": config.model.ollama_temperature,
        "image_backend": config.model.image_backend,
        "ollama_image_model": config.model.ollama_image_model,
        "enabled_loras": config.model.lora.enabled_loras,
        "available_loras": get_available_loras(config.model.lora.lora_dir),
        "lora_application_probability": config.model.lora.application_probability,
        "lora_dir": str(config.model.lora.lora_dir),
        "zimage_model_path": str(config.model.zimage_model_path),
        "zimage_native_available": zimage_native_source_path().exists(),
        "qwen_image_model": config.model.qwen_image_model,
        "qwen_prompt_magic": config.model.qwen_prompt_magic,
        "qwen_device_map": config.model.qwen_device_map,
        "qwen_lightning": config.model.qwen_lightning,
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
            "metadata": catalog_entry.get("metadata", {}),
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
    enable_plugins: bool = Field(True, description="Enable plugin enhancements")
    seed: Optional[int] = Field(None, description="Random seed for reproducibility")
    client_request_id: Optional[str] = Field(
        None, description="Client-provided request ID used to correlate progress events"
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
    publication_state: str = Field("draft", description="Initial publication state")
    client_request_id: Optional[str] = Field(
        None, description="Client-provided request ID used to correlate progress events"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extra job metadata")


class PublicationUpdateRequest(BaseModel):
    """Request model for changing gallery publication state."""

    state: str = Field(..., description="Publication state for this image")
    allow_placeholder_publish: bool = Field(
        False,
        description="Allow publishing mock/test placeholder images when explicitly requested",
    )


class EditRequest(BaseModel):
    """Request model for image editing"""

    prompt: str = Field(..., description="Edit prompt describing desired changes")
    strength: float = Field(0.8, ge=0.0, le=1.0, description="Edit strength (0.0 to 1.0)")


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


class PluginInfo(BaseModel):
    """Plugin information model"""

    name: str
    enabled: bool
    description: str
    order: int


class PluginOrderRequest(BaseModel):
    """Request model for plugin ordering."""

    ordered_names: List[str] = Field(..., description="Plugin names in desired execution order")


class PromptResponse(BaseModel):
    """Response model for prompt generation."""

    prompt: str = Field(..., description="Generated prompt text")


class SystemStatus(BaseModel):
    """System status model"""

    status: str = Field(..., description="System status (ready, busy, error)")
    backend: str = Field(..., description="Active backend (mock, flux)")
    plugins_enabled: bool
    active_plugins: List[str]
    gpu_available: bool
    ollama_available: bool


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
generation_worker_lock = asyncio.Lock()


def record_generation_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Record a lightweight lifecycle event for recent operator diagnostics."""
    payload = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **event,
    }
    recent_generation_events.appendleft(payload)
    return payload


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
            result = await service.generate(job_payload.to_service_request(job_id), callback=emit)
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


async def prefetch_default_fallback_model() -> None:
    """Fetch the default public fallback model in the background when needed."""
    if resolve_image_backend(config) != "small":
        return

    if is_model_cached(config.model.small_sd_model):
        return

    try:
        from huggingface_hub import snapshot_download

        logger.info("Prefetching small fallback model: %s", config.model.small_sd_model)
        await asyncio.to_thread(snapshot_download, repo_id=config.model.small_sd_model)
        logger.info("Small fallback model is ready")
    except Exception as e:
        logger.warning("Small fallback prefetch failed: %s", e)


@app.on_event("startup")
async def startup_event() -> None:
    generation_job_store.initialize()
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

    backend_name = backend_label(config, resolve_image_backend(config))

    return SystemStatus(
        status="ready",
        backend=backend_name,
        plugins_enabled=True,
        active_plugins=[name for name, info in plugin_manager.plugins.items() if info.enabled],
        gpu_available=gpu_available,
        ollama_available=ollama_available,
    )


@app.get("/api/plugins", response_model=List[PluginInfo])
async def get_plugins():
    """Get list of available plugins and their states"""
    plugins = []
    sorted_plugins = sorted(
        plugin_manager.plugins.values(), key=lambda info: (info.order, info.name)
    )
    for info in sorted_plugins:
        plugins.append(
            PluginInfo(
                name=info.name,
                enabled=info.enabled,
                description=info.description,
                order=info.order,
            )
        )
    return plugins


@app.get("/api/models/status")
async def get_model_status():
    """Get status of available models and their download progress"""
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


@app.post("/api/models/{model_id}/download")
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
                if local_dir is not None:
                    await loop.run_in_executor(
                        None,
                        lambda: snapshot_download(repo_id=resolved_model_id, local_dir=local_dir),
                    )
                else:
                    await loop.run_in_executor(
                        None,
                        lambda: snapshot_download(repo_id=resolved_model_id),
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

    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    try:
        # Save token to HF cache directory
        # Use configured HF_HOME or fallback
        hf_cache_dir = Path(os.getenv("HF_HOME", os.path.expanduser("~/.cache/huggingface")))
        hf_cache_dir.mkdir(parents=True, exist_ok=True)
        token_file = hf_cache_dir / "token"

        with open(token_file, "w") as f:
            f.write(token)

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
    if os.getenv("HF_TOKEN"):
        return {"configured": True, "source": "environment"}

    # Check token file using configured HF_HOME
    hf_cache_dir = Path(os.getenv("HF_HOME", os.path.expanduser("~/.cache/huggingface")))
    token_file = hf_cache_dir / "token"

    if token_file.exists():
        return {"configured": True, "source": "file"}

    return {"configured": False, "source": None}


@app.post("/api/plugins/{plugin_name}/toggle")
async def toggle_plugin(plugin_name: str):
    """Toggle a plugin on/off"""
    if plugin_name not in plugin_manager.plugins:
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
        current_prompt = resolve_ollama_model(models, config.model.ollama_model, "completion")
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
        # Update config
        config.model.ollama_model = model_name

        # Also update environment variable for persistence
        os.environ["OLLAMA_MODEL"] = model_name

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

        logger.info(f"Generation config updated: {data}")
        return {
            "message": "Configuration updated successfully",
            "config": generation_config_payload(),
        }
    except Exception as e:
        logger.error(f"Failed to update generation config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update configuration: {str(e)}")


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
    job = generation_job_store.create_job(
        GenerationJobCreate(
            prompt=request.prompt,
            seed=request.seed,
            client_request_id=request.client_request_id,
        )
    )
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
    job = generation_job_store.create_job(
        GenerationJobCreate(
            prompt=request.prompt,
            meta_prompt=request.meta_prompt,
            seed=request.seed,
            publication_state=request.publication_state,
            client_request_id=request.client_request_id,
            metadata=request.metadata,
        )
    )
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
    return {"events": events, "total": len(recent_generation_events), "limit": limit}


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

    page_entries = []
    for entry in entries[offset : offset + limit]:
        payload = dict(entry)
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
            allow_placeholder_publish=request.allow_placeholder_publish,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Catalog entry not found") from exc

    return entry


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


@app.post("/api/edit", response_model=EditResponse)
async def edit_image(request: EditRequest, file: UploadFile = File(...)):
    """Edit an uploaded image using Qwen-Image-Edit"""
    edit_id = str(uuid.uuid4())

    try:
        # Broadcast start event
        await manager.broadcast(
            json.dumps(
                {"type": "edit_started", "id": edit_id, "timestamp": datetime.now().isoformat()}
            )
        )

        # Read uploaded file
        image_bytes = await file.read()

        # Initialize image editor
        from src.generators.image_editor import ImageEditor

        editor = ImageEditor(config)

        # Broadcast editing event
        await manager.broadcast(
            json.dumps({"type": "editing_image", "id": edit_id, "prompt": request.prompt})
        )

        # Edit the image
        edited_image = await editor.edit_image(image_bytes, request.prompt, request.strength)

        # Save both original and edited images
        import io

        original_img = Image.open(io.BytesIO(image_bytes))
        original_path = save_image_and_prompt(
            original_img, f"ORIGINAL: {request.prompt}", str(OUTPUT_DIR)
        )
        register_image(
            original_path,
            OUTPUT_DIR,
            prompt=f"ORIGINAL: {request.prompt}",
            metadata={"operation": "edit_original"},
            publication_state="draft",
        )

        # Save edited
        edited_path = save_image_and_prompt(
            edited_image, f"EDITED: {request.prompt}", str(OUTPUT_DIR)
        )
        register_image(
            edited_path,
            OUTPUT_DIR,
            prompt=f"EDITED: {request.prompt}",
            metadata={"operation": "edit_result"},
            publication_state="draft",
        )

        # Create relative paths for API response
        original_relative = f"/images/{original_path.relative_to(OUTPUT_DIR).as_posix()}"
        edited_relative = f"/images/{edited_path.relative_to(OUTPUT_DIR).as_posix()}"

        # Broadcast completion event
        await manager.broadcast(
            json.dumps(
                {
                    "type": "edit_completed",
                    "id": edit_id,
                    "original_path": original_relative,
                    "edited_path": edited_relative,
                    "prompt": request.prompt,
                }
            )
        )

        return EditResponse(
            id=edit_id,
            prompt=request.prompt,
            original_path=original_relative,
            edited_path=edited_relative,
            metadata={
                "model": "Qwen/Qwen-Image-Edit",
                "strength": request.strength,
                "original_filename": file.filename,
            },
            created_at=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Image edit failed: {str(e)}")

        # Broadcast error event
        await manager.broadcast(json.dumps({"type": "edit_error", "id": edit_id, "error": str(e)}))

        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    # Run the server
    uvicorn.run("src.api.server:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
