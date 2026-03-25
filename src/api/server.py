"""
FastAPI server for Continuous Image Generation
Provides REST API and WebSocket endpoints for the Next.js frontend
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.generators.factory import (
    backend_label,
    create_image_generator,
    is_model_cached,
    resolve_image_backend,
)
from src.generators.prompt_generator import PromptGenerator
from src.plugins import plugin_manager, register_lora_plugin
from src.utils.config import Config
from src.utils.storage import StorageManager, save_image_and_prompt

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Output directory setup
OUTPUT_DIR = config.system.output_dir
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files for serving generated images
app.mount("/images", StaticFiles(directory=str(OUTPUT_DIR)), name="images")


# Pydantic models
class GenerateRequest(BaseModel):
    """Request model for image generation"""

    prompt: Optional[str] = Field(None, description="Optional custom prompt")
    enable_plugins: bool = Field(True, description="Enable plugin enhancements")
    seed: Optional[int] = Field(None, description="Random seed for reproducibility")


class GenerateResponse(BaseModel):
    """Response model for image generation"""

    id: str = Field(..., description="Unique generation ID")
    prompt: str = Field(..., description="Final prompt used")
    image_path: str = Field(..., description="Path to generated image")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Generation metadata")
    created_at: str = Field(..., description="ISO timestamp")


class EditRequest(BaseModel):
    """Request model for image editing"""

    prompt: str = Field(..., description="Edit prompt describing desired changes")
    strength: float = Field(0.8, ge=0.0, le=1.0, description="Edit strength (0.0 to 1.0)")


class PromptRequest(BaseModel):
    """Request model for prompt generation."""

    meta_prompt: Optional[str] = Field(
        None, description="Optional system prompt used to steer prompt generation"
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
            "downloadable": False,
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
            "id": "Qwen/Qwen-Image",
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

    try:
        from huggingface_hub import snapshot_download

        # Start download in background
        async def download_in_background():
            try:
                logger.info(f"Starting download for model: {model_id}")
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
                await loop.run_in_executor(
                    None, lambda: snapshot_download(repo_id=model_id, resume_download=True)
                )

                logger.info(f"Download completed for model: {model_id}")
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

        return {"message": f"Download started for {model_id}", "model_id": model_id}

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
        import ollama

        # Get list of models from Ollama
        models_response = ollama.list()

        # Extract model information
        models = []
        for model in models_response.get("models", []):
            models.append(
                {
                    "name": model.get("name") or model.get("model", ""),
                    "size": model.get("size", 0),
                    "modified": model.get("modified_at", ""),
                    "digest": model.get("digest", ""),
                }
            )

        # Get current model from config
        current_model = config.model.ollama_model

        return {
            "models": models,
            "current": current_model,
            "host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
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
    return {
        "width": config.image.width,
        "height": config.image.height,
        "num_inference_steps": config.image.num_inference_steps,
        "guidance_scale": config.image.guidance_scale,
        "true_cfg_scale": config.image.true_cfg_scale,
        "ollama_temperature": config.model.ollama_temperature,
    }


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

        logger.info(f"Generation config updated: {data}")
        return {"message": "Configuration updated successfully", "config": data}
    except Exception as e:
        logger.error(f"Failed to update generation config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update configuration: {str(e)}")


@app.post("/api/prompt", response_model=PromptResponse)
async def generate_prompt(request: PromptRequest):
    """Generate a prompt without creating an image."""
    try:
        prompt_gen = PromptGenerator(config)
        prompt = await prompt_gen.generate_prompt(meta_prompt=request.meta_prompt)
        return PromptResponse(prompt=prompt)
    except Exception as e:
        logger.error(f"Prompt generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_image(request: GenerateRequest):
    """Generate a single image"""
    generation_id = str(uuid.uuid4())

    try:
        # Broadcast start event
        await manager.broadcast(
            json.dumps(
                {
                    "type": "generation_started",
                    "id": generation_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        )

        # Generate prompt if not provided
        if request.prompt:
            final_prompt = request.prompt
        else:
            prompt_gen = PromptGenerator(config)
            final_prompt = await prompt_gen.generate_prompt()

            # Broadcast prompt generated event
            await manager.broadcast(
                json.dumps(
                    {"type": "prompt_generated", "id": generation_id, "prompt": final_prompt}
                )
            )

        try:
            image_gen, backend_name = create_image_generator(config)
            logger.info("Using image backend: %s", backend_name)
        except MemoryError as e:
            error_msg = "Insufficient memory to load the configured image backend."
            logger.error(f"Memory error loading Flux model: {str(e)}")
            await manager.broadcast(
                json.dumps({"type": "generation_error", "id": generation_id, "error": error_msg})
            )
            raise HTTPException(status_code=507, detail=error_msg)
        except Exception as e:
            error_msg = f"Failed to load image backend: {str(e)}"
            logger.error(error_msg)
            await manager.broadcast(
                json.dumps({"type": "generation_error", "id": generation_id, "error": error_msg})
            )
            raise HTTPException(status_code=500, detail=error_msg)

        backend_name = backend_label(config, resolve_image_backend(config))
        loading_message = {
            "mock": "Using mock image generator.",
            "smoke-test": "Loading smoke-test image model.",
            "small-sd": "Loading small Stable Diffusion fallback model.",
            "sd-turbo": "Loading turbo image model.",
        }.get(backend_name, "Loading Flux model (this may take several minutes on first run)...")

        await manager.broadcast(
            json.dumps(
                {
                    "type": "model_loading",
                    "id": generation_id,
                    "message": loading_message,
                }
            )
        )

        # Generate and save the image through the active backend.
        storage = StorageManager(str(OUTPUT_DIR))
        requested_output_path = storage.get_output_path(final_prompt)
        image_path, _, _ = await image_gen.generate_image(
            final_prompt,
            requested_output_path,
            force_reinit=False,
            seed=request.seed,
        )

        # Create relative path for API response
        relative_path = f"/images/{image_path.relative_to(OUTPUT_DIR).as_posix()}"

        # Broadcast completion event
        await manager.broadcast(
            json.dumps(
                {
                    "type": "generation_completed",
                    "id": generation_id,
                    "image_path": relative_path,
                    "prompt": final_prompt,
                }
            )
        )

        return GenerateResponse(
            id=generation_id,
            prompt=final_prompt,
            image_path=relative_path,
            metadata={
                "backend": backend_name,
                "plugins_used": [
                    name for name, info in plugin_manager.plugins.items() if info.enabled
                ],
                "seed": request.seed,
            },
            created_at=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Generation failed: {str(e)}")

        # Broadcast error event
        await manager.broadcast(
            json.dumps({"type": "generation_error", "id": generation_id, "error": str(e)})
        )

        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/gallery")
async def get_gallery(limit: int = 50, offset: int = 0):
    """Get list of generated images"""
    images = []
    last_image: Optional[Dict[str, Any]] = None

    # Get all image files from output directory
    image_files = sorted(OUTPUT_DIR.glob("**/*.png"), key=lambda x: x.stat().st_mtime, reverse=True)

    for image_file in image_files:
        # Check if corresponding prompt file exists
        prompt_file = image_file.with_suffix(".txt")
        prompt = ""
        if prompt_file.exists():
            try:
                async with aiofiles.open(prompt_file, "r", encoding="utf-8", errors="ignore") as f:
                    prompt = await f.read()
            except Exception as e:
                logger.warning(f"Failed to read prompt file {prompt_file}: {e}")
                prompt = "Could not read prompt"

        created_at = datetime.fromtimestamp(image_file.stat().st_mtime).isoformat()
        image_entry = {
            "path": f"/images/{image_file.relative_to(OUTPUT_DIR).as_posix()}",
            "prompt": prompt.strip(),
            "created_at": created_at,
            "size": image_file.stat().st_size,
        }

        # Collapse historical double-saves created by older API behavior.
        if last_image is not None:
            created_delta = abs(
                (
                    datetime.fromisoformat(last_image["created_at"])
                    - datetime.fromisoformat(image_entry["created_at"])
                ).total_seconds()
            )
            if (
                image_entry["prompt"] == last_image["prompt"]
                and image_entry["size"] == last_image["size"]
                and created_delta <= 8
            ):
                continue

        images.append(image_entry)
        last_image = image_entry

    paginated_images = images[offset : offset + limit]

    return {"images": paginated_images, "total": len(images), "limit": limit, "offset": offset}


@app.delete("/api/gallery/{image_path:path}")
async def delete_image(image_path: str):
    """Delete an image from the gallery"""
    full_path = (OUTPUT_DIR / image_path).resolve()
    output_root = OUTPUT_DIR.resolve()

    if not full_path.is_relative_to(output_root):
        raise HTTPException(status_code=400, detail="Invalid image path")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    # Delete image and prompt files
    full_path.unlink()
    prompt_path = full_path.with_suffix(".txt")
    if prompt_path.exists():
        prompt_path.unlink()

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

        # Save original
        from PIL import Image

        from src.utils.storage import save_image_and_prompt

        original_img = Image.open(io.BytesIO(image_bytes))
        original_path = save_image_and_prompt(
            original_img, f"ORIGINAL: {request.prompt}", str(OUTPUT_DIR)
        )

        # Save edited
        edited_path = save_image_and_prompt(
            edited_image, f"EDITED: {request.prompt}", str(OUTPUT_DIR)
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
