"""Local HTTP adapter for Microsoft's code and pinned Mage-Flow artifacts."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import io
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from huggingface_hub import hf_hub_download, snapshot_download
from PIL import Image
from pydantic import BaseModel, Field

MODEL_ID = os.getenv("MAGEFLOW_MODEL", "microsoft/Mage-Flow")
MODEL_REVISION = os.getenv(
    "MAGEFLOW_MODEL_REVISION",
    "faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
)
SOURCE_SHA = os.getenv("MAGEFLOW_SOURCE_SHA", "unknown")
ATTENTION = os.getenv("MAGEFLOW_ATTENTION", "sdpa")
MIN_VRAM_GB = float(os.getenv("MAGEFLOW_MIN_VRAM_GB", "20"))
PINNED_EDIT_MIRROR_REPOSITORY = "Comfy-Org/Mage-Flow"
PINNED_EDIT_MIRROR_REVISION = "dbba082792fb61234d7218327511a9725b69db37"
PINNED_EDIT_CONFIG_REPOSITORY = "mage-flow-community/Mage-Flow-Edit"
PINNED_EDIT_CONFIG_REVISION = "fd7119d80fff2e5be21178edf2a93877955540b9"
EDIT_MIRROR_REPOSITORY = os.getenv("MAGEFLOW_EDIT_MIRROR_REPOSITORY", PINNED_EDIT_MIRROR_REPOSITORY)
EDIT_MIRROR_REVISION = os.getenv(
    "MAGEFLOW_EDIT_MIRROR_REVISION",
    PINNED_EDIT_MIRROR_REVISION,
)
EDIT_CONFIG_REPOSITORY = os.getenv("MAGEFLOW_EDIT_CONFIG_REPOSITORY", PINNED_EDIT_CONFIG_REPOSITORY)
EDIT_CONFIG_REVISION = os.getenv(
    "MAGEFLOW_EDIT_CONFIG_REVISION",
    PINNED_EDIT_CONFIG_REVISION,
)
EDIT_PROVENANCE_STATUS = "user_authorized_comfy_org_mirror"
TEXT_ENCODER_ARTIFACT = {
    "path": "text_encoders/qwen3vl_4b_bf16.safetensors",
    "sha256": "36f3ff447ef59201722e8f9ce6020c9819fdcfba6aa2608c4e09b1c0ce114e34",
    "bytes": 8875719384,
}
VAE_ARTIFACT = {
    "path": "vae/mage_flow_vae_bf16.safetensors",
    "sha256": "34e076dc1e8a15321e1e07be5111d59cf16dd10b804b7c7e20b4de29013427e0",
    "bytes": 345053056,
}

app = FastAPI(title="DreamGen Mage-Flow Runtime")
_pipeline: Any = None
_pipeline_model_id: str | None = None
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


EDIT_MODELS = {
    "base": {
        "model_id": "microsoft/Mage-Flow-Edit-Base",
        "revision": os.getenv("MAGEFLOW_EDIT_BASE_REVISION", EDIT_MIRROR_REVISION).strip(),
        "artifact_repository": EDIT_MIRROR_REPOSITORY,
        "artifact_path": "diffusion_models/mage_flow_edit_base_bf16.safetensors",
        "artifact_sha256": "9d93faa75963ba4a2ef1b64bed4fe94c2554b82e8f3fb2dbb267604a634d450d",
        "artifact_bytes": 8231536784,
        "steps": 30,
        "cfg": 5.0,
    },
    "aligned": {
        "model_id": "microsoft/Mage-Flow-Edit",
        "revision": os.getenv("MAGEFLOW_EDIT_ALIGNED_REVISION", EDIT_MIRROR_REVISION).strip(),
        "artifact_repository": EDIT_MIRROR_REPOSITORY,
        "artifact_path": "diffusion_models/mage_flow_edit_bf16.safetensors",
        "artifact_sha256": "09cee4afa95239d850af02c9b1c006bffc71dca4a984a2a1f56edff9282d53d3",
        "artifact_bytes": 8231536784,
        "steps": 30,
        "cfg": 5.0,
    },
    "turbo": {
        "model_id": "microsoft/Mage-Flow-Edit-Turbo",
        "revision": os.getenv("MAGEFLOW_EDIT_TURBO_REVISION", EDIT_MIRROR_REVISION).strip(),
        "artifact_repository": EDIT_MIRROR_REPOSITORY,
        "artifact_path": "diffusion_models/mage_flow_edit_turbo_bf16.safetensors",
        "artifact_sha256": "29c3726ecd64afe149eef28af3e27b6b40de52646bfd16757a37da4b6fbcf288",
        "artifact_bytes": 8231536760,
        "steps": 4,
        "cfg": 1.0,
    },
}


def _is_full_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value.lower())


def _edit_sources_are_pinned() -> bool:
    return (
        EDIT_MIRROR_REPOSITORY == PINNED_EDIT_MIRROR_REPOSITORY
        and EDIT_MIRROR_REVISION == PINNED_EDIT_MIRROR_REVISION
        and EDIT_CONFIG_REPOSITORY == PINNED_EDIT_CONFIG_REPOSITORY
        and EDIT_CONFIG_REVISION == PINNED_EDIT_CONFIG_REVISION
    )


def _cached_snapshot(model_id: str = MODEL_ID, revision: str = MODEL_REVISION) -> str | None:
    try:
        return snapshot_download(
            repo_id=model_id,
            revision=revision,
            local_files_only=True,
        )
    except Exception:
        return None


def _pinned_cache_path(repo_id: str, revision: str, relative_path: str = "") -> Path:
    """Resolve an exact HF snapshot path without relying on hub cache metadata.

    Windows-hosted Docker volumes preserve the snapshot links and blobs but may
    not preserve the metadata format expected by a newer huggingface_hub build.
    The commit SHA and repository name still give us an unambiguous local path.
    """
    repo_dir = f"models--{repo_id.replace('/', '--')}"
    return Path(os.getenv("HF_HOME", "/models")) / repo_dir / "snapshots" / revision / relative_path


def _cached_mirror_file(filename: str, revision: str = EDIT_MIRROR_REVISION) -> str | None:
    """Resolve one pinned Comfy-Org artifact without initiating network I/O."""
    pinned_path = _pinned_cache_path(EDIT_MIRROR_REPOSITORY, revision, filename)
    if pinned_path.is_file():
        return str(pinned_path)
    try:
        return hf_hub_download(
            repo_id=EDIT_MIRROR_REPOSITORY,
            filename=filename,
            revision=revision,
            local_files_only=True,
        )
    except Exception:
        return None


def _config_snapshot(*, local_files_only: bool) -> str | None:
    """Resolve only metadata needed to load the mirror's single-file weights."""
    pinned_path = _pinned_cache_path(EDIT_CONFIG_REPOSITORY, EDIT_CONFIG_REVISION)
    if (pinned_path / "model_index.json").is_file():
        return str(pinned_path)
    try:
        return snapshot_download(
            repo_id=EDIT_CONFIG_REPOSITORY,
            revision=EDIT_CONFIG_REVISION,
            allow_patterns=[
                "model_index.json",
                "transformer/config.json",
                "scheduler/*",
                "text_encoder/*.json",
                "text_encoder/*.txt",
            ],
            local_files_only=local_files_only,
        )
    except Exception:
        return None


def _cached_edit_assets(settings: dict[str, Any]) -> dict[str, str] | None:
    revision = str(settings["revision"])
    if not _edit_sources_are_pinned() or revision != PINNED_EDIT_MIRROR_REVISION:
        return None
    paths = {
        "transformer": _cached_mirror_file(str(settings["artifact_path"]), revision),
        "text_encoder": _cached_mirror_file(TEXT_ENCODER_ARTIFACT["path"], revision),
        "vae": _cached_mirror_file(VAE_ARTIFACT["path"], revision),
        "config": _config_snapshot(local_files_only=True),
    }
    return {key: str(value) for key, value in paths.items()} if all(paths.values()) else None


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_artifact(path: str, *, expected_sha256: str, expected_bytes: int) -> None:
    actual_bytes = os.path.getsize(path)
    if actual_bytes != expected_bytes:
        raise RuntimeError(
            f"Artifact size mismatch for {path}: expected {expected_bytes}, got {actual_bytes}"
        )
    actual_sha256 = _sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"Artifact SHA-256 mismatch for {path}: expected {expected_sha256}, got {actual_sha256}"
        )


def _download_edit_assets(settings: dict[str, Any]) -> dict[str, str]:
    revision = str(settings["revision"])
    if not _edit_sources_are_pinned() or revision != PINNED_EDIT_MIRROR_REVISION:
        raise RuntimeError(
            "Mirror/config repositories and revisions must match DreamGen's complete pin set"
        )
    paths = {
        "transformer": hf_hub_download(
            repo_id=EDIT_MIRROR_REPOSITORY,
            filename=str(settings["artifact_path"]),
            revision=revision,
        ),
        "text_encoder": hf_hub_download(
            repo_id=EDIT_MIRROR_REPOSITORY,
            filename=TEXT_ENCODER_ARTIFACT["path"],
            revision=revision,
        ),
        "vae": hf_hub_download(
            repo_id=EDIT_MIRROR_REPOSITORY,
            filename=VAE_ARTIFACT["path"],
            revision=revision,
        ),
    }
    config = _config_snapshot(local_files_only=False)
    if config is None:
        raise RuntimeError("Pinned Mage-Flow-Edit configuration metadata could not be downloaded")
    paths["config"] = config
    _validate_artifact(
        paths["transformer"],
        expected_sha256=str(settings["artifact_sha256"]),
        expected_bytes=int(settings["artifact_bytes"]),
    )
    _validate_artifact(
        paths["text_encoder"],
        expected_sha256=TEXT_ENCODER_ARTIFACT["sha256"],
        expected_bytes=TEXT_ENCODER_ARTIFACT["bytes"],
    )
    _validate_artifact(
        paths["vae"],
        expected_sha256=VAE_ARTIFACT["sha256"],
        expected_bytes=VAE_ARTIFACT["bytes"],
    )
    return paths


def _replace_with_symlink(target: Path, source: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    resolved = Path(source).resolve()
    try:
        target.symlink_to(resolved)
    except OSError:
        # Windows may disallow symlinks without Developer Mode. A hardlink still
        # preserves the no-copy invariant because overlays live under HF_HOME.
        os.link(resolved, target)


def _prepare_mirror_repo(settings: dict[str, Any]) -> str:
    """Build a no-copy Diffusers overlay around the pinned Comfy single files."""
    assets = _cached_edit_assets(settings)
    if assets is None:
        raise RuntimeError(
            "The complete pinned Comfy-Org mirror set and configuration metadata are not cached"
        )
    _validate_artifact(
        assets["transformer"],
        expected_sha256=str(settings["artifact_sha256"]),
        expected_bytes=int(settings["artifact_bytes"]),
    )
    _validate_artifact(
        assets["text_encoder"],
        expected_sha256=TEXT_ENCODER_ARTIFACT["sha256"],
        expected_bytes=TEXT_ENCODER_ARTIFACT["bytes"],
    )
    _validate_artifact(
        assets["vae"],
        expected_sha256=VAE_ARTIFACT["sha256"],
        expected_bytes=VAE_ARTIFACT["bytes"],
    )
    overlay = (
        Path(os.getenv("HF_HOME", "/models"))
        / "dreamgen-overlays"
        / EDIT_MIRROR_REVISION
        / str(settings["model_id"]).rsplit("/", 1)[-1]
    )
    overlay.mkdir(parents=True, exist_ok=True)
    config_root = Path(assets["config"])
    shutil.copy2(config_root / "model_index.json", overlay / "model_index.json")
    for directory in ("transformer", "scheduler", "text_encoder"):
        shutil.copytree(config_root / directory, overlay / directory, dirs_exist_ok=True)
    for stale in (
        overlay / "text_encoder" / "model.safetensors.index.json",
        overlay / "text_encoder" / "model-00001-of-00002.safetensors",
        overlay / "text_encoder" / "model-00002-of-00002.safetensors",
    ):
        if stale.exists() or stale.is_symlink():
            stale.unlink()
    _replace_with_symlink(
        overlay / "transformer" / "diffusion_pytorch_model.safetensors",
        assets["transformer"],
    )
    _replace_with_symlink(overlay / "text_encoder" / "model.safetensors", assets["text_encoder"])
    _replace_with_symlink(
        overlay / "vae" / "diffusion_pytorch_model.safetensors",
        assets["vae"],
    )
    return str(overlay)


def _cuda_status() -> dict[str, Any]:
    if not torch.cuda.is_available():
        return {"available": False, "reason": "CUDA is not available in the Mage-Flow sidecar"}
    total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    free_gb, _ = torch.cuda.mem_get_info()
    return {
        "available": True,
        "device": torch.cuda.get_device_name(0),
        "total_gb": round(total_gb, 2),
        "free_gb": round(free_gb / 1024**3, 2),
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
        "loaded_model_id": _pipeline_model_id,
        "loading": _loading,
        "downloading": _downloading,
        "cuda": cuda,
        "versions": {
            "torch": torch.__version__,
        },
        "compiler": compiler,
        "edit_models": {
            variant: {
                **settings,
                "revision": settings["revision"] if _is_full_sha(settings["revision"]) else None,
                "cached": bool(_cached_edit_assets(settings)),
                "available": bool(
                    os.getenv("MAGEFLOW_EDIT_ENABLED", "false").lower() == "true"
                    and _edit_sources_are_pinned()
                    and settings["revision"] == PINNED_EDIT_MIRROR_REVISION
                ),
                "provenance_status": EDIT_PROVENANCE_STATUS,
                "configuration_repository": EDIT_CONFIG_REPOSITORY,
                "configuration_revision": EDIT_CONFIG_REVISION,
            }
            for variant, settings in EDIT_MODELS.items()
        },
    }


def _load_pipeline(
    model_id: str = MODEL_ID,
    revision: str = MODEL_REVISION,
    *,
    edit_settings: dict[str, Any] | None = None,
) -> Any:
    global _pipeline, _pipeline_model_id, _loading, _last_error
    cache_key = (
        f"{model_id}@{EDIT_MIRROR_REPOSITORY}:{revision}:{edit_settings['artifact_path']}"
        if edit_settings
        else model_id
    )
    if _pipeline is not None and _pipeline_model_id == cache_key:
        return _pipeline

    with _lock:
        if _pipeline is not None and _pipeline_model_id == cache_key:
            return _pipeline
        if _pipeline is not None:
            _pipeline = None
            _pipeline_model_id = None
            gc.collect()
            torch.cuda.empty_cache()
        snapshot = (
            _prepare_mirror_repo(edit_settings)
            if edit_settings
            else _cached_snapshot(model_id, revision)
        )
        if snapshot is None:
            raise RuntimeError(f"{model_id} at verified revision {revision} is not cached.")
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
            _pipeline_model_id = cache_key
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


def _run_edit(
    sources: list[bytes],
    *,
    command: str,
    variant: str,
    seed: int,
    steps: int,
    guidance: float,
    max_size: int,
    negative_prompt: str,
    vl_cond_long_edge: int,
) -> tuple[bytes, dict[str, Any]]:
    if not 1 <= len(sources) <= 3:
        raise HTTPException(
            status_code=422,
            detail="Mage-Flow-Edit supports between one and three reference images",
        )
    settings = EDIT_MODELS[variant]
    revision = str(settings["revision"])
    if (
        os.getenv("MAGEFLOW_EDIT_ENABLED", "false").lower() != "true"
        or not _edit_sources_are_pinned()
        or revision != PINNED_EDIT_MIRROR_REVISION
    ):
        raise HTTPException(
            status_code=503,
            detail="Mage-Flow-Edit requires the explicitly authorized pinned Comfy-Org mirror revision.",
        )
    with _generation_lock:
        pipeline = _load_pipeline(str(settings["model_id"]), revision, edit_settings=settings)
        references = [Image.open(io.BytesIO(source)).convert("RGB") for source in sources]
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        images = pipeline.edit(
            [command],
            [references],
            neg_prompts=[negative_prompt or " "],
            seeds=[seed],
            steps=steps,
            cfg=guidance,
            max_size=max_size,
            vl_cond_long_edge=vl_cond_long_edge,
        )
        elapsed = time.perf_counter() - started
        output = io.BytesIO()
        images[0].save(output, format="PNG")
        peak_mb = (
            round(torch.cuda.max_memory_allocated() / 1024**2)
            if torch.cuda.is_available()
            else None
        )
        return output.getvalue(), {"elapsed_seconds": elapsed, "peak_vram_mb": peak_mb}


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


@app.post("/edit/models/{variant}/download")
def download_edit_model(variant: str) -> dict[str, Any]:
    """Download one pinned, explicitly authorized Comfy-Org mirror checkpoint."""
    global _downloading, _last_error
    if variant not in EDIT_MODELS:
        raise HTTPException(status_code=404, detail=f"Unknown edit variant: {variant}")
    settings = EDIT_MODELS[variant]
    revision = str(settings["revision"])
    if (
        os.getenv("MAGEFLOW_EDIT_ENABLED", "false").lower() != "true"
        or not _edit_sources_are_pinned()
        or revision != PINNED_EDIT_MIRROR_REVISION
    ):
        raise HTTPException(
            status_code=503,
            detail="Enable Mage-Flow-Edit with the exact pinned Comfy-Org mirror revision first.",
        )
    cached_assets = _cached_edit_assets(settings)
    with _lock:
        if cached_assets is None and _downloading:
            return {"status": "downloading", "variant": variant, **settings}
        if cached_assets is None:
            _downloading = True
            _last_error = None
    try:
        assets = cached_assets or _download_edit_assets(settings)
        overlay = _prepare_mirror_repo(settings)
        return {
            "status": "ready",
            "variant": variant,
            "model_id": settings["model_id"],
            "artifact_repository": EDIT_MIRROR_REPOSITORY,
            "artifact_path": settings["artifact_path"],
            "artifact_sha256": settings["artifact_sha256"],
            "model_revision": revision,
            "configuration_repository": EDIT_CONFIG_REPOSITORY,
            "configuration_revision": EDIT_CONFIG_REVISION,
            "overlay_path": overlay,
            "downloaded_paths": assets,
            "provenance_status": EDIT_PROVENANCE_STATUS,
        }
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        raise HTTPException(
            status_code=503, detail=f"Pinned mirror edit download failed: {exc}"
        ) from exc
    finally:
        _downloading = False


@app.post("/unload")
def unload() -> dict[str, Any]:
    """Release the sidecar-owned pipeline and CUDA allocator state."""
    global _pipeline, _pipeline_model_id
    with _generation_lock:
        with _lock:
            was_loaded = _pipeline is not None
            _pipeline = None
            _pipeline_model_id = None
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


@app.post("/edit")
async def edit(
    files: list[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),
    command: str = Form(...),
    variant: str = Form("turbo"),
    seed: int = Form(42),
    steps: int = Form(4),
    guidance: float = Form(1.0),
    max_size: int = Form(1024),
    negative_prompt: str = Form(""),
    vl_cond_long_edge: int = Form(384),
) -> Response:
    """Run one pinned Mage-Flow-Edit operation through the authorized mirror."""
    if variant not in EDIT_MODELS:
        raise HTTPException(status_code=422, detail=f"Unknown edit variant: {variant}")
    if not command.strip():
        raise HTTPException(status_code=422, detail="Edit command is required")
    if not 1 <= steps <= 50 or not 1.0 <= guidance <= 10.0:
        raise HTTPException(status_code=422, detail="Unsupported edit settings")
    if max_size not in {512, 768, 1024, 1536, 2048}:
        raise HTTPException(status_code=422, detail="Unsupported max_size")
    references = list(files or [])
    if file is not None:
        references.insert(0, file)
    if not 1 <= len(references) <= 3:
        raise HTTPException(
            status_code=422,
            detail="Mage-Flow-Edit supports between one and three reference images",
        )
    try:
        image, metrics = await asyncio.to_thread(
            _run_edit,
            [await reference.read() for reference in references],
            command=command.strip(),
            variant=variant,
            seed=seed,
            steps=steps,
            guidance=guidance,
            max_size=max_size,
            negative_prompt=negative_prompt,
            vl_cond_long_edge=vl_cond_long_edge,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Mage-Flow-Edit failed: {exc}") from exc
    settings = EDIT_MODELS[variant]
    return Response(
        image,
        media_type="image/png",
        headers={
            "X-DreamGen-Model": EDIT_MIRROR_REPOSITORY,
            "X-DreamGen-Upstream-Model": str(settings["model_id"]),
            "X-DreamGen-Model-Revision": str(settings["revision"]),
            "X-DreamGen-Artifact-Path": str(settings["artifact_path"]),
            "X-DreamGen-Artifact-SHA256": str(settings["artifact_sha256"]),
            "X-DreamGen-Provenance-Status": EDIT_PROVENANCE_STATUS,
            "X-DreamGen-Configuration-Repository": EDIT_CONFIG_REPOSITORY,
            "X-DreamGen-Configuration-Revision": EDIT_CONFIG_REVISION,
            "X-DreamGen-Source-SHA": SOURCE_SHA,
            "X-DreamGen-Elapsed-Seconds": f"{metrics['elapsed_seconds']:.4f}",
            "X-DreamGen-Peak-VRAM-MB": str(metrics["peak_vram_mb"] or "unknown"),
        },
    )
