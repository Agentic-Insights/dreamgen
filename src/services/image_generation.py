"""Core image generation service boundary shared by API, CLI, and jobs."""

from __future__ import annotations

import hashlib
import inspect
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from src.generators.factory import create_image_generator
from src.generators.prompt_generator import PromptGenerator
from src.plugins import plugin_manager
from src.plugins.lora import condition_prompt_for_lora
from src.utils.config import Config
from src.utils.generation_plan import GenerationPlan, resolve_generation_plan
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


@runtime_checkable
class PlannedImageBackend(Protocol):
    """Optional backend capability for consuming a locked generation plan."""

    def set_generation_plan(self, generation_plan: GenerationPlan) -> None:
        """Lock plugin and adapter choices for the next render."""


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
    output_path: Path | None = None
    add_to_gallery: bool = True


@dataclass(frozen=True)
class GenerationProgressEvent:
    """Structured progress event emitted during generation."""

    name: str
    progress: int | None = None
    label: str | None = None
    detail: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None


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


@dataclass(frozen=True)
class PromptResolution:
    """Resolved prompt text plus the model that produced it, when applicable."""

    prompt: str
    prompt_model: str | None = None


ProgressCallback = Callable[[GenerationProgressEvent], Awaitable[None] | None]


def _config_value(root: Any, *path: str, default: Any = None) -> Any:
    """Read a nested config attribute without assuming every test double is complete."""
    value = root
    for part in path:
        value = getattr(value, part, default)
        if value is default:
            return default
    return value


def _metadata_scalar(value: Any) -> Any:
    """Return a JSON-safe metadata value for config fields."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if type(value).__module__.startswith("unittest.mock"):
        return None
    return str(value)


def _metadata_list(value: Any) -> list[Any]:
    """Return a JSON-safe list for optional config sequences."""
    if not value or type(value).__module__.startswith("unittest.mock"):
        return []
    if isinstance(value, (list, tuple, set)):
        return [_metadata_scalar(item) for item in value]
    return [_metadata_scalar(value)]


def _prompt_fingerprint(
    *,
    prompt: str,
    backend: str,
    model_name: str,
    seed: int | None,
    width: int | None,
    height: int | None,
    steps: int | None,
    guidance_scale: float | None,
    true_cfg_scale: float | None,
) -> str:
    """Build a stable short key for grouping repeatable experiment runs."""
    payload = "|".join(
        str(value)
        for value in (
            prompt,
            backend,
            model_name,
            seed,
            width,
            height,
            steps,
            guidance_scale,
            true_cfg_scale,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def loading_message_for_backend(backend_name: str) -> str:
    """Return a user-facing lifecycle message for a backend label."""
    return {
        "mock": "Using mock image generator.",
        "smoke-test": "Loading smoke-test image model.",
        "small-sd": "Loading small Stable Diffusion fallback model.",
        "sd-turbo": "Loading turbo image model.",
        "ollama": "Requesting an image from the configured Ollama host.",
        "qwen-image": "Loading Qwen-Image typography model.",
        "ernie-image": "Loading ERNIE-Image Turbo prompt-enhanced model.",
        "mage-flow": "Loading Microsoft Mage-Flow in the isolated local CUDA runtime.",
    }.get(backend_name, "Loading Flux model (this may take several minutes on first run)...")


class ImageGenService:
    """Coordinates prompt resolution, backend generation, metadata, and catalog state."""

    def __init__(self, config: Config, output_dir: Path | None = None):
        self.config = config
        self.output_dir = output_dir or config.system.output_dir

    def _build_experiment_metadata(
        self,
        *,
        request: GenerationServiceRequest,
        final_prompt: str,
        backend_name: str,
        model_name: str,
        generation_time: float,
        generation_metadata: dict[str, Any],
        resolved_seed: int | None,
        active_plugins: list[str],
        prompt_model: str | None,
        generation_plan_metadata: dict[str, Any],
        operational_guards: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Capture the reproducibility envelope for one local model probe."""
        width = _metadata_scalar(_config_value(self.config, "image", "width"))
        height = _metadata_scalar(_config_value(self.config, "image", "height"))
        steps = _metadata_scalar(_config_value(self.config, "image", "num_inference_steps"))
        guidance_scale = _metadata_scalar(_config_value(self.config, "image", "guidance_scale"))
        true_cfg_scale = _metadata_scalar(_config_value(self.config, "image", "true_cfg_scale"))
        configured_backend = _metadata_scalar(
            _config_value(self.config, "model", "image_backend", default=backend_name)
        )
        configured_prompt_model = _metadata_scalar(
            _config_value(self.config, "model", "ollama_model")
        )
        prompt_model = _metadata_scalar(prompt_model)
        enabled_loras = _metadata_list(
            _config_value(self.config, "model", "lora", "enabled_loras", default=[])
        )
        lora_probability = _config_value(
            self.config, "model", "lora", "application_probability", default=None
        )
        lora_probability = _metadata_scalar(lora_probability)
        raw_quality_flags = request.metadata.get("quality_flags") or []
        if isinstance(raw_quality_flags, str):
            quality_flags = [flag.strip() for flag in raw_quality_flags.split(",") if flag.strip()]
        else:
            quality_flags = [str(flag).strip() for flag in raw_quality_flags if str(flag).strip()]
        diagnostic = backend_name in {"mock", "smoke-test"} or bool(
            generation_metadata.get("is_placeholder")
        )
        if diagnostic and "diagnostic" not in quality_flags:
            quality_flags.append("diagnostic")
        for guard in operational_guards or []:
            if guard.get("status") in {"warning", "failed"}:
                for flag in guard.get("details", {}).get("quality_flags", []):
                    if flag not in quality_flags:
                        quality_flags.append(flag)

        return {
            "id": _prompt_fingerprint(
                prompt=final_prompt,
                backend=backend_name,
                model_name=model_name,
                seed=resolved_seed,
                width=width,
                height=height,
                steps=steps,
                guidance_scale=guidance_scale,
                true_cfg_scale=true_cfg_scale,
            ),
            "label": request.metadata.get("experiment_label"),
            "prompt_family": request.metadata.get("prompt_family"),
            "prompt": {
                "source": "operator" if request.prompt else "generated",
                "meta_prompt": request.meta_prompt,
                "final": final_prompt,
                "model": prompt_model,
                "configured_model": configured_prompt_model,
            },
            "pipeline": {
                "configured_backend": configured_backend,
                "resolved_backend": backend_name,
                "model": model_name,
                "prompt_model": prompt_model,
                "configured_prompt_model": configured_prompt_model,
            },
            "parameters": {
                "seed": resolved_seed,
                "width": width,
                "height": height,
                "steps": steps,
                "guidance_scale": guidance_scale,
                "true_cfg_scale": true_cfg_scale,
            },
            "enhancers": {
                "plugins": active_plugins,
                "loras": enabled_loras,
                "lora_application_probability": lora_probability,
                "plugin_contributions": generation_plan_metadata["plugin_contributions"],
                "selected_lora": generation_plan_metadata["selected_lora"],
                "resolution": generation_plan_metadata["resolution"],
                "operational_guards": operational_guards or [],
            },
            "timing": {
                "generation_seconds": generation_time,
            },
            "diagnostic": diagnostic,
            "quality_flags": quality_flags,
        }

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
        generation_plan: GenerationPlan,
    ) -> PromptResolution:
        phase_started = time.perf_counter()
        if request.prompt:
            final_prompt = condition_prompt_for_lora(
                request.prompt,
                generation_plan.selected_lora,
            )
            await self._emit(
                callback,
                GenerationProgressEvent(
                    name="prompt_ready",
                    progress=24,
                    label="Prompt ready",
                    detail="Using the prompt you provided directly.",
                    payload={"prompt": final_prompt},
                    duration_ms=(time.perf_counter() - phase_started) * 1000,
                ),
            )
            return PromptResolution(prompt=final_prompt)

        await self._emit(
            callback,
            GenerationProgressEvent(
                name="prompt_generation_started",
                progress=24,
                label="Generating prompt",
                detail="Building a fresh prompt from Ollama and the active plugins.",
            ),
        )
        prompt_generator = PromptGenerator(self.config, generation_plan=generation_plan)
        prompt = await prompt_generator.generate_prompt(meta_prompt=request.meta_prompt)
        prompt = condition_prompt_for_lora(prompt, generation_plan.selected_lora)
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="prompt_generated",
                progress=40,
                label="Prompt ready",
                detail="The prompt is assembled. Preparing the image backend next.",
                payload={"prompt": prompt},
                duration_ms=(time.perf_counter() - phase_started) * 1000,
            ),
        )
        return PromptResolution(prompt=prompt, prompt_model=prompt_generator.model_name)

    async def generate(
        self,
        request: GenerationServiceRequest,
        callback: ProgressCallback | None = None,
        backend: ImageBackend | None = None,
        backend_name: str | None = None,
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

        plugins_enabled = request.metadata.get("plugins_enabled_requested") is not False
        generation_plan = resolve_generation_plan(
            self.config,
            plugins_enabled=plugins_enabled,
            seed=request.seed,
        )
        plan_metadata = generation_plan.to_metadata()
        pre_guards = plugin_manager.execute_guards(
            "pre",
            {
                "request": request,
                "seed": request.seed,
                "generation_plan": plan_metadata,
            },
        )
        failed_pre_guards = [guard for guard in pre_guards if guard["status"] == "failed"]
        if failed_pre_guards:
            raise RuntimeError(f"Generation blocked by operational guard: {failed_pre_guards}")
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="generation_plan_resolved",
                progress=16,
                label="Generation plan ready",
                detail="Plugin and LoRA choices are locked for this job.",
                payload={**plan_metadata, "operational_guards": pre_guards},
            ),
        )

        prompt_started = time.perf_counter()
        prompt_resolution = await self._resolve_prompt(request, callback, generation_plan)
        prompt_duration_ms = (time.perf_counter() - prompt_started) * 1000
        final_prompt = prompt_resolution.prompt
        backend_started = time.perf_counter()
        if backend is None:
            image_gen_raw, backend_name = create_image_generator(self.config)
            image_gen = cast(ImageBackend, image_gen_raw)
        else:
            if backend_name is None:
                raise ValueError("backend_name is required when passing a reusable backend")
            image_gen = backend
        if isinstance(image_gen, PlannedImageBackend):
            image_gen.set_generation_plan(generation_plan)
        elif backend_name == "z-image":
            raise RuntimeError("The Z-Image backend does not support job-locked generation plans")
        backend_duration_ms = (time.perf_counter() - backend_started) * 1000
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="backend_ready",
                progress=55,
                label="Backend ready",
                detail="The selected image backend is loaded and ready to render.",
                payload={"backend": backend_name},
                duration_ms=backend_duration_ms,
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
        requested_output_path = request.output_path or storage.get_output_path(final_prompt)
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="output_path_ready",
                payload={"output_path": requested_output_path},
            ),
        )
        render_started = time.perf_counter()
        generation_metadata: dict[str, Any] = {}
        try:
            image_path, generation_time, model_name = await image_gen.generate_image(
                final_prompt,
                requested_output_path,
                force_reinit=request.force_reinit,
                seed=request.seed,
            )
            if image_path.resolve() != requested_output_path.resolve():
                requested_output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(image_path), str(requested_output_path))
                for suffix in (".txt", ".meta.json"):
                    source_sidecar = image_path.with_suffix(suffix)
                    if source_sidecar.exists():
                        shutil.move(
                            str(source_sidecar),
                            str(requested_output_path.with_suffix(suffix)),
                        )
                image_path = requested_output_path
            # Snapshot mutable backend provenance before optional cleanup.
            generation_metadata = dict(getattr(image_gen, "last_generation_metadata", {}) or {})
        finally:
            if request.cleanup:
                image_gen.cleanup()
        render_duration_ms = (time.perf_counter() - render_started) * 1000
        finalizing_started = time.perf_counter()

        if backend_name == "z-image" and generation_plan.selected_lora is not None:
            expected_lora = generation_plan.selected_lora
            actual_lora = generation_metadata.get("selected_lora")
            if actual_lora not in {None, expected_lora.name}:
                raise RuntimeError(
                    "Z-Image rendered with a LoRA that differs from the locked generation plan: "
                    f"expected {expected_lora.name!r}, got {actual_lora!r}"
                )
            actual_path = generation_metadata.get("selected_lora_path")
            expected_path = expected_lora.path.resolve()
            if actual_path is not None and Path(actual_path).resolve() != expected_path:
                raise RuntimeError(
                    "Z-Image rendered with a LoRA path that differs from the locked generation "
                    f"plan: expected {expected_path}, got {actual_path}"
                )
            generation_metadata.update(
                {
                    "selected_lora": expected_lora.name,
                    "selected_lora_path": str(expected_path),
                    "selected_lora_keyword": expected_lora.keyword,
                    "selected_lora_kind": expected_lora.kind,
                    "selected_lora_trigger_placement": expected_lora.trigger_placement,
                    "selected_lora_trigger_required": expected_lora.trigger_required,
                    "lora_backend": "diffsynth",
                }
            )

        generation_plan_metadata = generation_plan.to_metadata(
            lora_backend=generation_metadata.get("lora_backend")
        )
        post_guards = plugin_manager.execute_guards(
            "post",
            {
                "image_path": image_path,
                "final_prompt": final_prompt,
                "backend": backend_name,
                "model_name": model_name,
                "generation_plan": generation_plan_metadata,
                "generation_metadata": generation_metadata,
            },
        )
        operational_guards = pre_guards + post_guards
        generation_metadata["operational_guards"] = operational_guards
        generation_metadata["generation_plan"] = generation_plan_metadata
        if generation_plan_metadata["selected_lora"] is not None:
            generation_metadata["lora_provenance"] = generation_plan_metadata["selected_lora"]
        seed_supported = generation_metadata.get("seed_supported", True)
        resolved_seed = generation_metadata.get("seed")
        if resolved_seed is None and request.seed is not None and seed_supported:
            resolved_seed = request.seed
        active_plugins = list(generation_plan.enabled_plugins)
        experiment_metadata = self._build_experiment_metadata(
            request=request,
            final_prompt=final_prompt,
            backend_name=backend_name,
            model_name=model_name,
            generation_time=generation_time,
            generation_metadata=generation_metadata,
            resolved_seed=resolved_seed,
            active_plugins=active_plugins,
            prompt_model=prompt_resolution.prompt_model,
            generation_plan_metadata=generation_plan_metadata,
            operational_guards=operational_guards,
        )

        existing_metadata = read_image_metadata(image_path)
        saved_metadata = {
            **existing_metadata,
            **request.metadata,
            **generation_metadata,
            "backend": backend_name,
            "configured_backend": self.config.model.image_backend,
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "seed": resolved_seed,
            "model": model_name,
            "generation_time": generation_time,
            "experiment": experiment_metadata,
            "quality_flags": experiment_metadata["quality_flags"],
        }
        write_image_metadata(image_path, saved_metadata)
        publication_entry = None
        if request.add_to_gallery:
            publication_entry = register_image(
                image_path,
                self.output_dir,
                prompt=final_prompt,
                metadata=saved_metadata,
                publication_state=request.publication_state,
            )
            relative_image_path = f"/images/{image_path.relative_to(self.output_dir).as_posix()}"
        else:
            relative_image_path = str(image_path.resolve())
        phase_durations_ms = {
            "prompt": round(prompt_duration_ms, 2),
            "backend": round(backend_duration_ms, 2),
            "render": round(render_duration_ms, 2),
            "finalize": round((time.perf_counter() - finalizing_started) * 1000, 2),
        }
        experiment_metadata["timing"]["phase_durations_ms"] = phase_durations_ms
        saved_metadata["experiment"] = experiment_metadata
        write_image_metadata(image_path, saved_metadata)
        await self._emit(
            callback,
            GenerationProgressEvent(
                name="finalizing_output",
                progress=92,
                label="Finalizing output",
                detail=(
                    "Saving metadata and writing the finished image to the gallery."
                    if request.add_to_gallery
                    else "Saving metadata for the ad-hoc output."
                ),
                payload={
                    "phase_durations_ms": phase_durations_ms,
                    "catalog": (
                        {
                            "id": publication_entry["id"],
                            "state": publication_entry["publication_state"],
                            "publishable": publication_entry["publishable"],
                        }
                        if publication_entry
                        else None
                    ),
                },
                duration_ms=phase_durations_ms["finalize"],
            ),
        )
        response_metadata = {
            **request.metadata,
            **generation_metadata,
            "backend": backend_name,
            "model": model_name,
            "generation_time": generation_time,
            "experiment": experiment_metadata,
            "quality_flags": experiment_metadata["quality_flags"],
            "publication": (
                {
                    "id": publication_entry["id"],
                    "state": publication_entry["publication_state"],
                    "publishable": publication_entry["publishable"],
                    "quality_flags": publication_entry["quality_flags"],
                }
                if publication_entry
                else {"state": "untracked", "publishable": False}
            ),
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
                    "model": model_name,
                    "generation_time": generation_time,
                    "phase_durations_ms": phase_durations_ms,
                    "selected_lora": generation_metadata.get("selected_lora"),
                    "lora_backend": generation_metadata.get("lora_backend"),
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
