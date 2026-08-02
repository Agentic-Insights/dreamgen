"""Centralized model readiness, memory, persistence, and cleanup controls."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

import psutil

from src.generators.factory import (
    backend_label,
    incomplete_model_downloads,
    inspect_local_zimage_model,
    is_model_cached,
    model_cache_path,
    resolve_image_backend,
)
from src.utils.config import Config
from src.utils.mageflow_runtime import (
    MAGEFLOW_MODEL_URL,
    MAGEFLOW_SOURCE_URL,
    probe_mageflow_runtime,
)


class ModelRuntimeManager:
    """Own runtime inspection and durable user-selected model configuration."""

    def __init__(self, config: Config, state_path: Path | None = None):
        self.config = config
        self.state_path = state_path or Path(
            os.getenv("RUNTIME_SELECTION_PATH", config.system.cache_dir / "runtime-selection.json")
        )

    def load_selection(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        for key in ("image_backend", "ollama_model", "ollama_image_model"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                setattr(self.config.model, key, value.strip())
        return data

    def persist_selection(self) -> dict[str, str]:
        payload = {
            "image_backend": self.config.model.image_backend,
            "ollama_model": self.config.model.ollama_model,
            "ollama_image_model": self.config.model.ollama_image_model,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
        return payload

    def _local_zimage(self) -> dict[str, Any]:
        path = self.config.model.zimage_model_path
        status, size = inspect_local_zimage_model(path)
        return {
            "status": status,
            "size": size,
            "path": str(path),
        }

    def _hf_model(self, model_id: str) -> dict[str, Any]:
        path = model_cache_path(model_id)
        incomplete = incomplete_model_downloads(model_id)
        status = (
            "downloading"
            if incomplete
            else (
                "ready"
                if is_model_cached(model_id)
                else ("partial" if path.exists() else "not_downloaded")
            )
        )
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0
        return {
            "status": status,
            "size": size,
            "incomplete_files": len(incomplete),
            "path": str(path) if path.exists() else None,
        }

    def _mageflow(self) -> dict[str, Any]:
        checkpoint = self._hf_model(self.config.model.mageflow_model)
        runtime = probe_mageflow_runtime(self.config.model.mageflow_url)
        checkpoint_status = checkpoint["status"]
        if checkpoint_status in {"not_downloaded", "downloading", "partial"}:
            status = checkpoint_status
            reason = "Download the public Mage-Flow checkpoint before enabling the isolated runtime"
        elif (
            runtime.get("ready")
            and runtime.get("model_id") == self.config.model.mageflow_model
            and runtime.get("model_revision") == self.config.model.mageflow_revision
        ):
            status = "ready"
            reason = runtime.get("reason") or "Checkpoint and isolated CUDA runtime are ready"
        else:
            status = str(runtime.get("status") or "runtime_unavailable")
            if (
                runtime.get("ready")
                and runtime.get("model_revision") != self.config.model.mageflow_revision
            ):
                status = "revision_mismatch"
                reason = (
                    "Mage-Flow runtime revision "
                    f"{runtime.get('model_revision') or 'unknown'} does not match verified revision "
                    f"{self.config.model.mageflow_revision}"
                )
            else:
                reason = runtime.get("reason") or "The isolated Mage-Flow runtime is not ready"
        return {
            **checkpoint,
            "status": status,
            "reason": reason,
            "runtime": runtime,
            "verified_revision": self.config.model.mageflow_revision,
            "source_url": MAGEFLOW_MODEL_URL,
            "implementation_url": MAGEFLOW_SOURCE_URL,
            "license": "MIT",
            "research_only": True,
        }

    def memory(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        result: dict[str, Any] = {
            "system": {
                "total_gb": round(vm.total / 1024**3, 2),
                "available_gb": round(vm.available / 1024**3, 2),
                "percent_used": vm.percent,
            },
            "cuda": {"available": False},
        }
        try:
            import torch

            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                result["cuda"] = {
                    "available": True,
                    "device": torch.cuda.get_device_name(0),
                    "total_gb": round(total / 1024**3, 2),
                    "free_gb": round(free / 1024**3, 2),
                    "allocated_gb": round(torch.cuda.memory_allocated() / 1024**3, 2),
                    "reserved_gb": round(torch.cuda.memory_reserved() / 1024**3, 2),
                }
        except Exception:
            pass
        return result

    def recommended(self, mageflow_status: dict[str, Any] | None = None) -> dict[str, Any]:
        memory = self.memory()
        vram = memory["cuda"].get("total_gb", 0)
        mageflow_status = mageflow_status or self._mageflow()
        backend = (
            "mageflow"
            if mageflow_status["status"] == "ready" and vram >= 20
            else (
                "zimage"
                if self._local_zimage()["status"] == "ready" and vram >= 16
                else (
                    "flux"
                    if is_model_cached(self.config.model.flux_model) and vram >= 20
                    else "small"
                )
            )
        )
        return {
            "backend": backend,
            "width": 1024 if vram >= 20 else 512,
            "height": 1024 if vram >= 20 else 512,
            "reason": (
                f"Selected for {vram:.1f} GB VRAM"
                if vram
                else "Selected from local cache availability"
            ),
        }

    def status(self) -> dict[str, Any]:
        mageflow_status = self._mageflow()
        specs = [
            ("flux", self.config.model.flux_model, "FLUX"),
            ("small", self.config.model.small_sd_model, "Small Stable Diffusion"),
            ("turbo", self.config.model.turbo_model, "SD Turbo"),
            ("smoke", self.config.model.smoke_test_model, "Smoke Test SD"),
        ]
        backends = []
        backends.append(
            {
                "backend": "mageflow",
                "id": self.config.model.mageflow_model,
                "name": "Microsoft Mage-Flow",
                "type": "text-to-image",
                "downloadable": True,
                **mageflow_status,
            }
        )
        for backend, model_id, name in specs:
            backends.append(
                {
                    "backend": backend,
                    "id": model_id,
                    "name": name,
                    "type": "text-to-image",
                    "downloadable": True,
                    **self._hf_model(model_id),
                }
            )
        backends.append(
            {
                "backend": "zimage",
                "id": "local:zimage",
                "name": "Z-Image-Turbo",
                "type": "text-to-image",
                "downloadable": True,
                "incomplete_files": 0,
                **self._local_zimage(),
            }
        )
        backends.extend(
            [
                {
                    "backend": "ollama",
                    "id": self.config.model.ollama_image_model or "ollama:image",
                    "name": "Ollama Image",
                    "type": "text-to-image",
                    "status": (
                        "configured" if self.config.model.ollama_image_model else "not_configured"
                    ),
                    "downloadable": False,
                    "size": 0,
                    "incomplete_files": 0,
                    "path": None,
                },
                {
                    "backend": "mock",
                    "id": "builtin:mock",
                    "name": "Mock",
                    "type": "text-to-image",
                    "status": "ready",
                    "downloadable": False,
                    "size": 0,
                    "incomplete_files": 0,
                    "path": None,
                },
            ]
        )
        resolved_backend = resolve_image_backend(
            self.config,
            mageflow_ready=mageflow_status["status"] == "ready",
        )
        active_model = next(
            (item for item in backends if item["backend"] == resolved_backend),
            None,
        )
        preferred_model = next(item for item in backends if item["backend"] == "mageflow")
        zimage_model = next(item for item in backends if item["backend"] == "zimage")
        flux_model = next(item for item in backends if item["backend"] == "flux")
        small_model = next(item for item in backends if item["backend"] == "small")
        fallback_model = (
            zimage_model
            if zimage_model["status"] == "ready"
            else flux_model if flux_model["status"] == "ready" else small_model
        )
        resolved_fallback = active_model or fallback_model
        fallback_reason = None
        if preferred_model["status"] != "ready" and self.config.model.image_backend == "auto":
            fallback_reason = (
                f"Mage-Flow unavailable: {preferred_model.get('reason') or preferred_model['status']}. "
                f"Using {resolved_fallback['name']} ({resolved_fallback['id']}) instead."
            )
        elif self.config.model.image_backend == "zimage" and resolved_backend != "zimage":
            fallback_reason = (
                f"Z-Image-Turbo unavailable at {zimage_model['path']}. "
                f"Using {resolved_fallback['name']} ({resolved_fallback['id']}) instead."
            )

        return {
            "configured_backend": self.config.model.image_backend,
            "resolved_backend": resolved_backend,
            "active_backend": resolved_backend,
            "active_backend_label": backend_label(self.config, resolved_backend),
            "active_model": active_model["name"] if active_model else resolved_backend,
            "active_model_id": active_model["id"] if active_model else resolved_backend,
            "active_model_status": active_model["status"] if active_model else "unknown",
            "preferred_backend": "mageflow",
            "preferred_model": preferred_model["name"],
            "preferred_model_id": preferred_model["id"],
            "preferred_model_status": preferred_model["status"],
            "fallback_backend": fallback_model["backend"],
            "fallback_model": fallback_model["name"],
            "fallback_model_id": fallback_model["id"],
            "fallback_reason": fallback_reason,
            "backends": backends,
            "models": backends,
            "cache_dir": str(model_cache_path("x").parent),
            "memory": self.memory(),
            "recommended": self.recommended(mageflow_status),
            "selection_path": str(self.state_path),
        }

    def unload(self) -> dict[str, Any]:
        sidecar: dict[str, Any]
        unload_request = request.Request(
            f"{self.config.model.mageflow_url.rstrip('/')}/unload",
            data=b"",
            method="POST",
        )
        try:
            with request.urlopen(unload_request, timeout=5.0) as response:
                sidecar = json.loads(response.read().decode("utf-8"))
        except (error.HTTPError, error.URLError, TimeoutError, OSError, ValueError) as exc:
            sidecar = {
                "status": "unavailable",
                "unloaded": False,
                "reason": f"Mage-Flow sidecar unload failed: {exc}",
            }

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                if torch.cuda.is_initialized():
                    torch.cuda.ipc_collect()
        except Exception:
            pass
        message = (
            "Runtime caches and Mage-Flow sidecar released"
            if sidecar.get("unloaded")
            else "Backend caches released; Mage-Flow sidecar was unavailable"
        )
        return {
            "message": message,
            "memory": self.memory(),
            "mageflow": sidecar,
        }
