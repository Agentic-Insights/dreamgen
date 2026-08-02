"""Small local-only HTTP adapter around Microsoft's pinned Mage-Flow source."""

from __future__ import annotations

import asyncio
import gc
import io
import os
import shutil
import threading
from pathlib import Path
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field

MODEL_ID = os.getenv("MAGEFLOW_MODEL", "microsoft/Mage-Flow")
MODEL_REVISION = os.getenv(
    "MAGEFLOW_MODEL_REVISION",
    "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
)
SOURCE_SHA = os.getenv("MAGEFLOW_SOURCE_SHA", "unknown")
ATTENTION = os.getenv("MAGEFLOW_ATTENTION", "sdpa")
MIN_VRAM_GB = float(os.getenv("MAGEFLOW_MIN_VRAM_GB", "20"))

app = FastAPI(title="DreamGen Mage-Flow Runtime")
_pipeline: Any = None
_loading = False
_downloading = False
_last_error: str | None = None
_lock = threading.Lock()
_generation_lock = threading.Lock()


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8192)
    model_id: str
    height: int = Field(ge=512, le=2048, multiple_of=16)
    width: int = Field(ge=512, le=2048, multiple_of=16)
    steps: int = Field(ge=1, le=50)
    guidance_scale: float = Field(ge=0, le=20)
    seed: int = Field(ge=0, le=2**31 - 1)


def _cached_snapshot() -> str | None:
    try:
        return snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            local_files_only=True,
        )
    except Exception:
        return None


def _cuda_status() -> dict[str, Any]:
    if not torch.cuda.is_available():
        return {"available": False, "reason": "CUDA is not available in the Mage-Flow sidecar"}
    total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    return {
        "available": True,
        "device": torch.cuda.get_device_name(0),
        "total_gb": round(total_gb, 2),
        "sufficient": total_gb >= MIN_VRAM_GB,
        "reason": (
            None
            if total_gb >= MIN_VRAM_GB
            else f"{total_gb:.1f} GB VRAM is below the {MIN_VRAM_GB:.1f} GB guardrail"
        ),
    }


def _health_payload() -> dict[str, Any]:
    snapshot = _cached_snapshot()
    cuda = _cuda_status()
    compiler = shutil.which("cc")
    runtime_compatible = bool(cuda.get("available") and cuda.get("sufficient") and compiler)
    if _downloading:
        status = "downloading"
        reason = "The public Mage-Flow checkpoint is downloading"
    elif _last_error:
        status = "runtime_error"
        reason = _last_error
    elif not runtime_compatible:
        status = "incompatible_runtime"
        reason = cuda.get("reason") or "A C compiler is required for Triton kernels"
    elif snapshot is None:
        status = "not_downloaded"
        reason = "The public Mage-Flow checkpoint is not fully cached"
    else:
        status = "ready"
        reason = "Checkpoint and isolated CUDA runtime are ready"
    return {
        "status": status,
        "reason": reason,
        "model_id": MODEL_ID,
        "verified_model_revision": MODEL_REVISION,
        "model_source": f"https://huggingface.co/{MODEL_ID}",
        "implementation_source": "https://github.com/microsoft/Mage",
        "source_sha": SOURCE_SHA,
        "license": "MIT",
        "research_only": True,
        "attention": ATTENTION,
        "checkpoint_path": snapshot,
        "model_revision": Path(snapshot).name if snapshot else None,
        "loaded": _pipeline is not None,
        "loading": _loading,
        "downloading": _downloading,
        "cuda": cuda,
        "versions": {
            "torch": torch.__version__,
        },
        "compiler": compiler,
    }


def _load_pipeline() -> Any:
    global _pipeline, _loading, _last_error
    if _pipeline is not None:
        return _pipeline

    with _lock:
        if _pipeline is not None:
            return _pipeline
        snapshot = _cached_snapshot()
        if snapshot is None:
            raise RuntimeError(
                "Mage-Flow is not cached. Download microsoft/Mage-Flow from DreamGen Settings first."
            )
        cuda = _cuda_status()
        if not cuda.get("available") or not cuda.get("sufficient"):
            raise RuntimeError(str(cuda.get("reason")))

        _loading = True
        _last_error = None
        try:
            # Upstream exposes an SDPA implementation but defaults its public loader
            # to FlashAttention. Inject the selected supported backend while keeping
            # Mage-Flow isolated from DreamGen's older Torch/Transformers stack.
            import mage_flow.pipeline as upstream_pipeline
            from mage_flow import MageFlowPipeline

            original_config = upstream_pipeline.ModelConfig

            def configured_model_config(*args: Any, **kwargs: Any):
                kwargs.setdefault("attn_type", ATTENTION)
                return original_config(*args, **kwargs)

            upstream_pipeline.ModelConfig = configured_model_config
            _pipeline = MageFlowPipeline.from_pretrained(snapshot, device="cuda")
            return _pipeline
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _loading = False


def _run_generation(payload: GenerateRequest) -> list[Any]:
    """Serialize generation and unload so CUDA memory cannot be freed mid-render."""
    with _generation_lock:
        pipeline = _load_pipeline()
        verdict = pipeline.model.txt_enc.screen_text(payload.prompt)
        if verdict.violates:
            categories = ", ".join(verdict.categories) or "unspecified"
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Mage-Flow's mandatory content-policy gate blocked the prompt",
                    "categories": categories,
                    "reason": verdict.reason or "No reason was returned",
                },
            )
        return pipeline.generate(
            [payload.prompt],
            heights=[payload.height],
            widths=[payload.width],
            seeds=[payload.seed],
            steps=payload.steps,
            cfg=payload.guidance_scale,
        )


@app.get("/health")
def health() -> dict[str, Any]:
    return _health_payload()


@app.post("/download")
def download() -> dict[str, Any]:
    """Download the public checkpoint through the writable sidecar cache mount."""
    global _downloading, _last_error
    with _lock:
        if _cached_snapshot() is not None:
            return {"status": "ready", "model_id": MODEL_ID}
        if _downloading:
            return {"status": "downloading", "model_id": MODEL_ID}
        _downloading = True
        _last_error = None

    try:
        snapshot = snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION)
        return {
            "status": "ready",
            "model_id": MODEL_ID,
            "model_revision": Path(snapshot).name,
        }
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        raise HTTPException(
            status_code=503, detail=f"Mage-Flow checkpoint download failed: {exc}"
        ) from exc
    finally:
        _downloading = False


@app.post("/unload")
def unload() -> dict[str, Any]:
    """Release the sidecar-owned pipeline and CUDA allocator state."""
    global _pipeline
    with _generation_lock:
        with _lock:
            was_loaded = _pipeline is not None
            _pipeline = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if torch.cuda.is_initialized():
                torch.cuda.ipc_collect()
    return {"status": "ready", "unloaded": True, "was_loaded": was_loaded}


@app.post("/generate")
async def generate(payload: GenerateRequest) -> Response:
    if payload.model_id != MODEL_ID:
        raise HTTPException(
            status_code=409,
            detail=f"Runtime is configured for {MODEL_ID}, not {payload.model_id}",
        )
    try:
        images = await asyncio.to_thread(_run_generation, payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Mage-Flow generation failed: {exc}") from exc

    buffer = io.BytesIO()
    images[0].save(buffer, format="PNG")
    snapshot = _cached_snapshot()
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={
            "X-DreamGen-Model": MODEL_ID,
            "X-DreamGen-Model-Revision": Path(snapshot).name if snapshot else "unknown",
            "X-DreamGen-Source-SHA": SOURCE_SHA,
        },
    )
