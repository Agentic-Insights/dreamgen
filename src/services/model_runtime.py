"""Centralized model readiness, memory, persistence, and cleanup controls."""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path
from typing import Any

import psutil

from src.generators.factory import (
    incomplete_model_downloads,
    is_model_cached,
    model_cache_path,
    resolve_image_backend,
)
from src.utils.config import Config


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
        complete = (
            (
                (path / "model_index.json").exists()
                and (path / "tokenizer" / "tokenizer.json").exists()
                and (path / "vae" / "diffusion_pytorch_model.safetensors").exists()
                and any((path / "transformer").glob("*.safetensors"))
                and any((path / "text_encoder").glob("*.safetensors"))
            )
            if path.exists()
            else False
        )
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0
        return {
            "status": "ready" if complete else ("partial" if path.exists() else "not_downloaded"),
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

    def recommended(self) -> dict[str, Any]:
        memory = self.memory()
        vram = memory["cuda"].get("total_gb", 0)
        backend = (
            "zimage"
            if self._local_zimage()["status"] == "ready" and vram >= 16
            else (
                "flux" if is_model_cached(self.config.model.flux_model) and vram >= 20 else "small"
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
        specs = [
            ("flux", self.config.model.flux_model, "FLUX"),
            ("small", self.config.model.small_sd_model, "Small Stable Diffusion"),
            ("turbo", self.config.model.turbo_model, "SD Turbo"),
            ("smoke", self.config.model.smoke_test_model, "Smoke Test SD"),
        ]
        backends = []
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
        return {
            "configured_backend": self.config.model.image_backend,
            "resolved_backend": resolve_image_backend(self.config),
            "backends": backends,
            "models": backends,
            "cache_dir": str(model_cache_path("x").parent),
            "memory": self.memory(),
            "recommended": self.recommended(),
            "selection_path": str(self.state_path),
        }

    def unload(self) -> dict[str, Any]:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                if torch.cuda.is_initialized():
                    torch.cuda.ipc_collect()
        except Exception:
            pass
        return {"message": "Runtime caches released", "memory": self.memory()}
