"""Core image generation service boundary shared by API, CLI, and jobs."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast

from src.generators.factory import create_image_generator
from src.generators.prompt_generator import PromptGenerator
from src.plugins import plugin_manager
from src.utils.config import Config
from src.utils.publication_catalog import register_image
from src.utils.storage import StorageManager, read_image_metadata, write_image_metadata


class ImageBackend(Protocol):
    """Generation backend interface used by the service."""

    last_generation_metadata: dict[str, Any]

    async def generate_image(
        self,
        prompt: str,
        output_path: Path,
        force_reinit: bool = False,
        seed: int | None = None,
    ) -> tuple[Path, float, str]:
        """Generate and save an image."""

    def cleanup(self) -> None:
        """Release backend resources."""


@dataclass(frozen=True)
class GenerationServiceRequest:
    """Input for a single image generation workflow."""

    prompt: str | None = None
    meta_prompt: str | None = None
    seed: int | None = None
    force_reinit: bool = False
    publication_state: str = "draft"
    cleanup: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationProgressEvent:
    """Structured progress event emitted during generation."""

    name: str
    progress: int | None = None
    label: str | None = None
    detail: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationServiceResult:
    """Result from a completed generation workflow."""

    prompt: str
    image_path: Path
    relative_image_path: str
    backend: str
    model_name: str
    generation_time: float
    metadata: dict[str, Any]
    publication: dict[str, Any]
    created_at: str


ProgressCallback = Callable[[GenerationProgressEvent], Awaitable[None] | None]


def loading_message_for_backend(backend_name: str) -> str:
    """Return a user-facing lifecycle message for a backend label."""
    return {
        "mock": "Using mock image generator.",
        "smoke-test": "Loading smoke-test image model.",
        "small-sd": "Loading small Stable Diffusion fallback model.",
        "sd-turbo": "Loading turbo image model.",
        "ollama": "Requesting an image from the configured Ollama host.",
    }.get(backend_name, "Loading Flux model (this may take several minutes on first run)...")


class ImageGenService:
    """Coordinates prompt resolution, backend generation, metadata, and catalog state."""

    def __init__(self, config: Config, output_dir: Path | None = None):
        self.config = config
        self.output_dir = output_dir or config.system.output_dir

    async def _emit(
        self,
        callback: ProgressCallback | None,
        event: GenerationProgressEvent,
    ) -> None:
        if callback is None:
            return
        result = callback(event)
        if inspect.isawaitable(result):
            await result

    async def _resolve_prompt(
        self,
        request: GenerationServiceRequest,
        callback: ProgressCallback | None,
    ) -> str:
        if request.prompt:
            await self._emit(
                callback,
                GenerationProgressEvent(
                    name="prompt_ready",
                    progress=24,
                    label="Prompt ready",
                    detail="Using the prompt you provided directly.",
                    payload={"prompt": request.prompt},
                ),
            )
            return request.prompt

        await self._emit(
            callback,
            GenerationProgressEvent(
                name="prompt_generation_started",
                progress=24,
                label="Generating prompt",
                detail="Building a fresh prompt from Ollama and the active plugins.",
            ),
        )
        prompt = await PromptGenerator(self.config).generate_prompt(meta_prompt=request.meta_prompt)
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="prompt_generated",
                progress=40,
                label="Prompt ready",
                detail="The prompt is assembled. Preparing the image backend next.",
                payload={"prompt": prompt},
            ),
        )
        return prompt

    async def generate(
        self,
        request: GenerationServiceRequest,
        callback: ProgressCallback | None = None,
    ) -> GenerationServiceResult:
        """Run one generation workflow and return persisted artifact details."""
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="generation_preparing",
                progress=8,
                label="Preparing image request",
                detail="Collecting the prompt, active plugins, and runtime settings.",
            ),
        )

        final_prompt = await self._resolve_prompt(request, callback)
        image_gen_raw, backend_name = create_image_generator(self.config)
        image_gen = cast(ImageBackend, image_gen_raw)
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="backend_ready",
                progress=55,
                label="Backend ready",
                detail="The selected image backend is loaded and ready to render.",
                payload={"backend": backend_name},
            ),
        )

        loading_message = loading_message_for_backend(backend_name)
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="model_loading",
                progress=68,
                label="Rendering image",
                detail=loading_message,
                payload={"backend": backend_name, "message": loading_message},
            ),
        )

        storage = StorageManager(str(self.output_dir))
        requested_output_path = storage.get_output_path(final_prompt)
        try:
            image_path, generation_time, model_name = await image_gen.generate_image(
                final_prompt,
                requested_output_path,
                force_reinit=request.force_reinit,
                seed=request.seed,
            )
        finally:
            if request.cleanup:
                image_gen.cleanup()

        await self._emit(
            callback,
            GenerationProgressEvent(
                name="finalizing_output",
                progress=92,
                label="Finalizing output",
                detail="Saving metadata and writing the finished image to the gallery.",
            ),
        )

        generation_metadata = getattr(image_gen, "last_generation_metadata", {}) or {}
        seed_supported = generation_metadata.get("seed_supported", True)
        resolved_seed = generation_metadata.get("seed")
        if resolved_seed is None and request.seed is not None and seed_supported:
            resolved_seed = request.seed

        existing_metadata = read_image_metadata(image_path)
        saved_metadata = {
            **existing_metadata,
            **request.metadata,
            **generation_metadata,
            "backend": backend_name,
            "configured_backend": self.config.model.image_backend,
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "seed": resolved_seed,
        }
        write_image_metadata(image_path, saved_metadata)
        publication_entry = register_image(
            image_path,
            self.output_dir,
            prompt=final_prompt,
            metadata=saved_metadata,
            publication_state=request.publication_state,
        )
        relative_image_path = f"/images/{image_path.relative_to(self.output_dir).as_posix()}"
        active_plugins = [name for name, info in plugin_manager.plugins.items() if info.enabled]
        response_metadata = {
            **generation_metadata,
            "backend": backend_name,
            "publication": {
                "id": publication_entry["id"],
                "state": publication_entry["publication_state"],
                "publishable": publication_entry["publishable"],
                "quality_flags": publication_entry["quality_flags"],
            },
            "plugins_used": active_plugins,
            "seed": resolved_seed,
        }
        created_at = datetime.now().isoformat()

        await self._emit(
            callback,
            GenerationProgressEvent(
                name="generation_completed",
                progress=100,
                label="Image ready",
                detail="The generated image is saved and ready to review.",
                payload={
                    "image_path": relative_image_path,
                    "prompt": final_prompt,
                    "backend": backend_name,
                },
            ),
        )

        return GenerationServiceResult(
            prompt=final_prompt,
            image_path=image_path,
            relative_image_path=relative_image_path,
            backend=backend_name,
            model_name=model_name,
            generation_time=generation_time,
            metadata=response_metadata,
            publication=response_metadata["publication"],
            created_at=created_at,
        )
