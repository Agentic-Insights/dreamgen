"""Provider-neutral, immutable identity contract for planned image engines.

This catalog intentionally separates upstream weight availability from DreamGen
runtime readiness. A public checkpoint is not selectable until it has a dedicated
adapter and target-hardware evidence; no existing backend may impersonate it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ImageEngineDescriptor:
    """Verified identity and integration state for one upstream engine."""

    id: str
    display_name: str
    provider: str
    repository: str
    revision: str
    license: str
    role: str
    operations: tuple[str, ...]
    pipeline_class: str
    source_repository: str
    source_revision: str
    weights_public: bool
    dreamgen_adapter: str | None
    selectable: bool
    integration_state: str
    integration_reason: str
    supported_controls: tuple[str, ...]
    defaults: dict[str, int | float]
    upstream_vram_claims_gb: tuple[int, ...]
    dreamgen_supported_vram_gb: int
    measured_on_target: bool
    safetensors_bytes: int
    safetensors_files: int
    primary_sources: tuple[str, ...]


FLUX2_KLEIN_4B = ImageEngineDescriptor(
    id="flux2-klein-4b",
    display_name="FLUX.2 [klein] 4B",
    provider="Black Forest Labs",
    repository="black-forest-labs/FLUX.2-klein-4B",
    revision="e7b7dc27f91deacad38e78976d1f2b499d76a294",
    license="Apache-2.0",
    role="target_default",
    operations=("text-to-image", "single-reference-edit", "multi-reference-edit"),
    pipeline_class="diffusers.Flux2KleinPipeline",
    source_repository="black-forest-labs/flux2",
    source_revision="50fe5162777813d869182b139e83b10743caef15",
    weights_public=True,
    dreamgen_adapter=None,
    selectable=False,
    integration_state="adapter_pending",
    integration_reason=(
        "The official weights are public, but DreamGen's locked Diffusers revision predates "
        "Flux2KleinPipeline and the existing flux backend is a FLUX.1 adapter."
    ),
    supported_controls=(
        "prompt",
        "seed",
        "width",
        "height",
        "num_inference_steps",
        "reference_images",
    ),
    defaults={"width": 1024, "height": 1024, "num_inference_steps": 4, "guidance_scale": 1.0},
    # BFL currently publishes both ~8 GB (source README) and ~13 GB (model card).
    upstream_vram_claims_gb=(8, 13),
    dreamgen_supported_vram_gb=24,
    measured_on_target=False,
    safetensors_bytes=23_715_318_326,
    safetensors_files=5,
    primary_sources=(
        "https://huggingface.co/black-forest-labs/FLUX.2-klein-4B",
        "https://github.com/black-forest-labs/flux2",
        "https://huggingface.co/docs/diffusers/api/pipelines/flux2",
    ),
)


LONGCAT_IMAGE = ImageEngineDescriptor(
    id="longcat-image",
    display_name="LongCat-Image",
    provider="Meituan LongCat",
    repository="meituan-longcat/LongCat-Image",
    revision="d2ea50b79a930074c37b9b97ce45e3b2ea8cf4d8",
    license="Apache-2.0",
    role="benchmark_lane",
    operations=("text-to-image",),
    pipeline_class="diffusers.LongCatImagePipeline",
    source_repository="meituan-longcat/LongCat-Image",
    source_revision="f0e4c43c5ef74b011ff71570fbfc2bdffbc9ab06",
    weights_public=True,
    dreamgen_adapter=None,
    selectable=False,
    integration_state="benchmark_pending",
    integration_reason="Benchmark lane only; it is not a DreamGen production backend.",
    supported_controls=("prompt", "seed", "width", "height", "num_inference_steps"),
    defaults={"width": 1024, "height": 1024, "num_inference_steps": 50, "guidance_scale": 4.0},
    upstream_vram_claims_gb=(17,),
    dreamgen_supported_vram_gb=24,
    measured_on_target=False,
    safetensors_bytes=29_293_491_646,
    safetensors_files=7,
    primary_sources=(
        "https://huggingface.co/meituan-longcat/LongCat-Image",
        "https://github.com/meituan-longcat/LongCat-Image",
    ),
)


QWEN_IMAGE_EDIT_2511 = ImageEngineDescriptor(
    id="qwen-image-edit-2511",
    display_name="Qwen-Image-Edit-2511",
    provider="Qwen",
    repository="Qwen/Qwen-Image-Edit-2511",
    revision="6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9",
    license="Apache-2.0",
    role="benchmark_lane",
    operations=("single-reference-edit", "multi-reference-edit"),
    pipeline_class="diffusers.QwenImageEditPlusPipeline",
    source_repository="QwenLM/Qwen-Image",
    source_revision="6b5e1f5cec987d404be5ac6657db3b9aacb56a89",
    weights_public=True,
    dreamgen_adapter=None,
    selectable=False,
    integration_state="benchmark_pending",
    integration_reason="Edit benchmark lane only; it is not Mage-Flow-Edit or a generation default.",
    supported_controls=(
        "prompt",
        "negative_prompt",
        "seed",
        "num_inference_steps",
        "true_cfg_scale",
        "reference_images",
    ),
    defaults={"num_inference_steps": 40, "guidance_scale": 1.0, "true_cfg_scale": 4.0},
    upstream_vram_claims_gb=(),
    dreamgen_supported_vram_gb=24,
    measured_on_target=False,
    safetensors_bytes=57_699_249_798,
    safetensors_files=10,
    primary_sources=(
        "https://huggingface.co/Qwen/Qwen-Image-Edit-2511",
        "https://github.com/QwenLM/Qwen-Image",
    ),
)


IMAGE_ENGINE_CANDIDATES = (FLUX2_KLEIN_4B, LONGCAT_IMAGE, QWEN_IMAGE_EDIT_2511)


def image_engine_catalog() -> dict[str, Any]:
    """Return the API contract for planned engines without overstating readiness."""

    return {
        "schema_version": 1,
        "target_default": FLUX2_KLEIN_4B.id,
        "target_default_selectable": FLUX2_KLEIN_4B.selectable,
        "benchmark_lanes": [LONGCAT_IMAGE.id, QWEN_IMAGE_EDIT_2511.id],
        "policy": {
            "no_aliasing": True,
            "no_implicit_fallback": True,
            "activation_requires": [
                "dedicated_adapter",
                "full_revision_pin",
                "artifact_hash_verification",
                "rtx_4090_measurement",
                "deterministic_smoke_test",
            ],
            "diffusers_first_klein_commit": "61f175660a8ac54f1470a74a810e6c38fb4795d5",
        },
        "engines": [asdict(engine) for engine in IMAGE_ENGINE_CANDIDATES],
    }
