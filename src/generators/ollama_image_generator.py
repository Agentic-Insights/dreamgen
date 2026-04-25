"""Image generator backed by Ollama's experimental image API."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from ..utils.config import Config
from ..utils.error_handler import ModelError
from ..utils.ollama import (
    OllamaRequestError,
    generate_image_via_ollama,
    list_ollama_models,
    resolve_ollama_model,
)

logger = logging.getLogger(__name__)


class OllamaImageGenerator:
    """Generate images through an external Ollama host."""

    def __init__(self, config: Config):
        self.config = config
        self.model_name = config.model.ollama_image_model
        self.width = config.image.width
        self.height = config.image.height
        self.last_generation_metadata: dict = {}

    def initialize(self, force_reinit: bool = False) -> None:  # noqa: D401 - stub
        """No-op initialize to mirror the local pipeline-backed generators."""
        return None

    async def generate(self, prompt: str, seed: Optional[int] = None) -> Image.Image:
        from ..utils.storage import StorageManager

        storage = StorageManager()
        output_path = storage.get_output_path(prompt)
        await self.generate_image(prompt, output_path, force_reinit=False, seed=seed)
        return Image.open(output_path)

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        force_reinit: bool = False,
        seed: Optional[int] = None,
    ) -> Tuple[Path, float, str]:
        del force_reinit  # No persistent pipeline to reinitialize.

        start = time.time()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        models = await asyncio.to_thread(list_ollama_models)
        model_name = resolve_ollama_model(models, self.config.model.ollama_image_model, "image")
        if not model_name:
            raise ModelError(
                "No Ollama image model is available. Install an image-capable model such as "
                "'x/z-image-turbo' or 'x/flux2-klein'."
            )

        try:
            image = await asyncio.to_thread(
                generate_image_via_ollama,
                model_name=model_name,
                prompt=prompt,
                width=self.width,
                height=self.height,
            )
        except OllamaRequestError as exc:
            raise ModelError(str(exc)) from exc

        image.save(output_path)
        output_path.with_suffix(".txt").write_text(prompt, encoding="utf-8")

        self.last_generation_metadata = {
            "provider": "ollama",
            "ollama_model": model_name,
            "seed_supported": False,
            "requested_seed": seed,
        }

        if (
            self.config.model.ollama_image_model
            and self.config.model.ollama_image_model != model_name
        ):
            logger.warning(
                "Configured Ollama image model %s is unavailable or not image-capable; using %s instead",
                self.config.model.ollama_image_model,
                model_name,
            )

        return output_path, time.time() - start, model_name

    def cleanup(self) -> None:
        self.last_generation_metadata = {}
