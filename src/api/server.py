"""
FastAPI server for Continuous Image Generation
Provides REST API and WebSocket endpoints for the Next.js frontend
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.generators.image_generator import ImageGenerator
from src.generators.prompt_generator import PromptGenerator
from src.plugins import initialize_plugins, plugin_manager
from src.utils.config import Config
from src.utils.storage import save_image_and_prompt

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Continuous Image Generator API",
    description="API for AI-powered image generation with plugin architecture",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Configure CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:22023",  # Docker frontend port
        "http://localhost:3000",  # Next.js default dev server
        "http://localhost:3001",  # Alternative port
        "http://localhost:7860",  # Legacy port
        "https://imagegen.agenticinsights.com",  # Production
        "https://dreamgen.agenticinsights.com",  # Production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
config = Config()
state = {"use_mock": False}  # Use real Flux generation with GPU

# Initialize plugins with config
initialize_plugins(config)

# Output directory setup
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

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
            except:
                pass  # Handle disconnected clients


manager = ConnectionManager()


# API Endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Continuous Image Generator API",
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
    except:
        gpu_available = False

    # Check Ollama availability
    try:
        import ollama

        ollama_available = True
    except:
        ollama_available = False

    # Determine which Flux model is being used
    if state["use_mock"]:
        backend_name = "mock"
    else:
        flux_model = config.model.flux_model
        if "schnell" in flux_model.lower():
            backend_name = "flux-schnell"
        elif "dev" in flux_model.lower():
            backend_name = "flux-dev"
        else:
            backend_name = "flux"

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
    for name, info in plugin_manager.plugins.items():
        plugins.append(PluginInfo(name=name, enabled=info.enabled, description=info.description))
    return plugins


@app.get("/api/models/status")
async def get_model_status():
    """Get status of available models and their download progress"""
    import os
    from pathlib import Path

    hf_cache_dir = Path(os.getenv("HF_HUB_CACHE", os.path.expanduser("~/.cache/huggingface/hub")))

    models = []
    model_configs = [
        {"id": "Qwen/Qwen-Image", "name": "Qwen-Image", "type": "text-to-image"},
        {"id": "Qwen/Qwen-Image-Edit", "name": "Qwen-Image-Edit", "type": "image-to-image"},
        {
            "id": "black-forest-labs/FLUX.1-schnell",
            "name": "FLUX.1 Schnell",
            "type": "text-to-image",
        },
        {"id": "black-forest-labs/FLUX.1-dev", "name": "FLUX.1 Dev", "type": "text-to-image"},
    ]

    for model_config in model_configs:
        model_id = model_config["id"]
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
                except:
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
        # Import huggingface_hub for downloading
        import asyncio

        from huggingface_hub import hf_hub_download, snapshot_download

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
        import os
        from pathlib import Path

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
    import os
    from pathlib import Path

    # Check environment variable first
    if os.getenv("HF_TOKEN"):
        return {"configured": True, "source": "environment"}

    # Check token file
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

        # Generate image
        logger.info("Using REAL Flux image generator")

        # Broadcast model loading event
        await manager.broadcast(
            json.dumps(
                {
                    "type": "model_loading",
                    "id": generation_id,
                    "message": "Loading Flux model (this may take several minutes on first run)...",
                }
            )
        )

        try:
            image_gen = ImageGenerator(config)
        except MemoryError as e:
            error_msg = (
                "Insufficient memory to load Flux model. This model requires significant RAM/VRAM."
            )
            logger.error(f"Memory error loading Flux model: {str(e)}")
            await manager.broadcast(
                json.dumps({"type": "generation_error", "id": generation_id, "error": error_msg})
            )
            raise HTTPException(status_code=507, detail=error_msg)
        except Exception as e:
            error_msg = f"Failed to load Flux model: {str(e)}"
            logger.error(error_msg)
            await manager.broadcast(
                json.dumps({"type": "generation_error", "id": generation_id, "error": error_msg})
            )
            raise HTTPException(status_code=500, detail=error_msg)

        # Generate the image
        image = await image_gen.generate(final_prompt, seed=request.seed)

        # Save image and prompt
        image_path = save_image_and_prompt(image, final_prompt)

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

        # Determine backend name
        flux_model = config.model.flux_model
        if "schnell" in flux_model.lower():
            backend_name = "flux-schnell"
        elif "dev" in flux_model.lower():
            backend_name = "flux-dev"
        else:
            backend_name = "flux"

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

    # Get all image files from output directory
    image_files = sorted(OUTPUT_DIR.glob("**/*.png"), key=lambda x: x.stat().st_mtime, reverse=True)

    # Apply pagination
    paginated_files = image_files[offset : offset + limit]

    for image_file in paginated_files:
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

        images.append(
            {
                "path": f"/images/{image_file.relative_to(OUTPUT_DIR).as_posix()}",
                "prompt": prompt.strip(),
                "created_at": datetime.fromtimestamp(image_file.stat().st_mtime).isoformat(),
                "size": image_file.stat().st_size,
            }
        )

    return {"images": images, "total": len(image_files), "limit": limit, "offset": offset}


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
            request = GenerateRequest(use_mock=state["use_mock"])
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
        original_path = save_image_and_prompt(original_img, f"ORIGINAL: {request.prompt}")

        # Save edited
        edited_path = save_image_and_prompt(edited_image, f"EDITED: {request.prompt}")

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
