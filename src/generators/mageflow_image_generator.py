"""Client backend for the isolated local Microsoft Mage-Flow runtime."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from typing import Optional
from urllib import error, request

from src.utils.config import Config
from src.utils.mageflow_runtime import MAGEFLOW_MODEL_URL, MAGEFLOW_SOURCE_URL


class MageFlowImageGenerator:
    """Generate images through DreamGen's local CUDA-only Mage-Flow sidecar."""

    def __init__(self, config: Config):
        self.config = config
        self.model_name = config.model.mageflow_model
        self.runtime_url = config.model.mageflow_url.rstrip("/")
        self.timeout = config.model.mageflow_timeout_seconds
        self.height = self._dimension(config.image.height)
        self.width = self._dimension(config.image.width)
        self.steps = config.model.mageflow_steps
        self.guidance_scale = config.model.mageflow_cfg
        self.last_generation_metadata: dict = {}

    @staticmethod
    def _dimension(value: int) -> int:
        """Clamp to Mage-Flow's documented native-resolution range and alignment."""
        return max(512, min(2048, int(value))) // 16 * 16

    def _post_generate(self, payload: dict) -> tuple[bytes, dict[str, str]]:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self.runtime_url}/generate",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "image/png"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                headers = {
                    "model_revision": response.headers.get("X-DreamGen-Model-Revision", ""),
                    "source_sha": response.headers.get("X-DreamGen-Source-SHA", ""),
                }
                return response.read(), headers
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Mage-Flow runtime rejected generation ({exc.code}): {detail}"
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"Mage-Flow runtime is unavailable at {self.runtime_url}; "
                "the request was not relabeled as a successful fallback."
            ) from exc

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        force_reinit: bool = False,
        seed: Optional[int] = None,
    ) -> tuple[Path, float, str]:
        del force_reinit
        resolved_seed = seed if seed is not None else secrets.randbelow(2**31 - 1)
        payload = {
            "prompt": prompt,
            "model_id": self.model_name,
            "height": self.height,
            "width": self.width,
            "steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "seed": resolved_seed,
        }

        started = time.perf_counter()
        image_bytes, provenance = await asyncio.to_thread(self._post_generate, payload)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        output_path.with_suffix(".txt").write_text(prompt, encoding="utf-8")
        elapsed = time.perf_counter() - started

        self.last_generation_metadata = {
            "backend": "mageflow",
            "model": self.model_name,
            "model_source": MAGEFLOW_MODEL_URL,
            "implementation_source": MAGEFLOW_SOURCE_URL,
            "model_revision": provenance["model_revision"] or None,
            "verified_model_revision": self.config.model.mageflow_revision,
            "implementation_revision": provenance["source_sha"] or None,
            "runtime": self.runtime_url,
            "seed": resolved_seed,
            "seed_supported": True,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "isolated_runtime": True,
        }
        return output_path, elapsed, self.model_name.split("/")[-1]

    def cleanup(self) -> None:
        """The sidecar owns model memory; the client has no local CUDA state."""
