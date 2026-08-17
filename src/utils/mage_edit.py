"""Truthful capability and availability contract for Mage-Flow-Edit."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

OFFICIAL_SOURCE_REPOSITORY = "https://github.com/microsoft/Mage"
OFFICIAL_SOURCE_REVISION = "76bec2bb3818863f470de7e867c2dc7f1d0bfd83"
OFFICIAL_LICENSE = "MIT"
MIRROR_REPOSITORY = "Comfy-Org/Mage-Flow"
MIRROR_REVISION = "dbba082792fb61234d7218327511a9725b69db37"
MIRROR_PROVENANCE_STATUS = "user_authorized_comfy_org_mirror"
CONFIG_REPOSITORY = "mage-flow-community/Mage-Flow-Edit"
CONFIG_REVISION = "fd7119d80fff2e5be21178edf2a93877955540b9"
UNVERIFIED_COMMUNITY_REPOSITORIES = (
    "mage-flow-community/Mage-Flow-Edit-Base",
    "mage-flow-community/Mage-Flow-Edit",
    "mage-flow-community/Mage-Flow-Edit-Turbo",
)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class MageEditVariant:
    id: str
    label: str
    upstream_repository: str
    artifact_path: str
    artifact_sha256: str
    artifact_bytes: int
    default_steps: int
    default_guidance: float
    revision_env: str

    def descriptor(self) -> dict[str, Any]:
        revision = os.environ.get(self.revision_env, MIRROR_REVISION).strip().lower()
        verified_revision = revision if FULL_SHA.fullmatch(revision) else None
        enabled = os.getenv("MAGEFLOW_EDIT_ENABLED", "false").lower() == "true"
        available = bool(enabled and verified_revision == MIRROR_REVISION)
        return {
            **asdict(self),
            "repository": MIRROR_REPOSITORY,
            "artifact_repository": MIRROR_REPOSITORY,
            "verified_revision": verified_revision,
            "available": available,
            "availability_reason": (
                None
                if available
                else ("Enable the user-authorized Comfy-Org mirror at its pinned full revision.")
            ),
        }


VARIANTS = (
    MageEditVariant(
        id="base",
        label="Base",
        upstream_repository="microsoft/Mage-Flow-Edit-Base",
        artifact_path="diffusion_models/mage_flow_edit_base_bf16.safetensors",
        artifact_sha256="9d93faa75963ba4a2ef1b64bed4fe94c2554b82e8f3fb2dbb267604a634d450d",
        artifact_bytes=8231536784,
        default_steps=30,
        default_guidance=5.0,
        revision_env="MAGEFLOW_EDIT_BASE_REVISION",
    ),
    MageEditVariant(
        id="aligned",
        label="Aligned",
        upstream_repository="microsoft/Mage-Flow-Edit",
        artifact_path="diffusion_models/mage_flow_edit_bf16.safetensors",
        artifact_sha256="09cee4afa95239d850af02c9b1c006bffc71dca4a984a2a1f56edff9282d53d3",
        artifact_bytes=8231536784,
        default_steps=30,
        default_guidance=5.0,
        revision_env="MAGEFLOW_EDIT_ALIGNED_REVISION",
    ),
    MageEditVariant(
        id="turbo",
        label="Turbo",
        upstream_repository="microsoft/Mage-Flow-Edit-Turbo",
        artifact_path="diffusion_models/mage_flow_edit_turbo_bf16.safetensors",
        artifact_sha256="29c3726ecd64afe149eef28af3e27b6b40de52646bfd16757a37da4b6fbcf288",
        artifact_bytes=8231536760,
        default_steps=4,
        default_guidance=1.0,
        revision_env="MAGEFLOW_EDIT_TURBO_REVISION",
    ),
)


def capability_document() -> dict[str, Any]:
    """Return the single capability document consumed by API, CLI, and Studio."""
    variants = [variant.descriptor() for variant in VARIANTS]
    return {
        "feature": "Mage-Edit",
        "official_name": "Mage-Flow-Edit",
        "source_repository": OFFICIAL_SOURCE_REPOSITORY,
        "source_revision": OFFICIAL_SOURCE_REVISION,
        "license": OFFICIAL_LICENSE,
        "research_only": True,
        "checkpoint_source": {
            "repository": MIRROR_REPOSITORY,
            "revision": MIRROR_REVISION,
            "url": f"https://huggingface.co/{MIRROR_REPOSITORY}",
            "provenance_status": MIRROR_PROVENANCE_STATUS,
            "license_claim": "MIT",
        },
        "configuration_source": {
            "repository": CONFIG_REPOSITORY,
            "revision": CONFIG_REVISION,
            "weights_used": False,
            "purpose": "Diffusers layout and tokenizer metadata for the Comfy-Org single files",
        },
        "target_hardware": "NVIDIA RTX 4090-class GPU with 24 GB VRAM or better",
        "model_loaded": False,
        "queue_depth": 0,
        "gpu": {"available": False, "name": None, "vram_total_mb": None, "vram_free_mb": None},
        "controls": {
            "command": {"type": "string", "required": True},
            "reference_images": {"type": "image", "minimum": 1, "maximum": 3},
            "seed": {"type": "integer", "minimum": 0},
            "steps": {"type": "integer", "minimum": 1, "maximum": 50},
            "guidance": {"type": "number", "minimum": 1.0, "maximum": 10.0},
            "max_size": {"type": "integer", "options": [512, 768, 1024, 1536, 2048]},
            "negative_prompt": {"type": "string", "required": False},
            "vl_cond_long_edge": {"type": "integer", "default": 384},
        },
        "unsupported_controls": ["strength"],
        "edit_modes": [
            "semantic and localized content editing",
            "scene, subject, and camera transformations",
            "appearance and artistic transformations",
            "low-level conditional reconstruction and restoration",
            "multi-reference editing (trained with up to three references)",
        ],
        "variants": variants,
        "available": any(variant["available"] for variant in variants),
        "provenance_status": MIRROR_PROVENANCE_STATUS,
        "unverified_community_repositories": list(UNVERIFIED_COMMUNITY_REPOSITORIES),
        "access_note": (
            "The official Microsoft Hugging Face repositories currently return 404 in a "
            "signed-in session rather than presenting a standard access agreement. The operator "
            "explicitly authorized Comfy-Org/Mage-Flow as a mirror. DreamGen records that mirror, "
            "its immutable revision, file path, and SHA-256 separately from the Microsoft upstream "
            "identity; it is never presented as Microsoft-hosted. Configuration/tokenizer metadata "
            "comes from the audited aligned community duplicate, with none of its weights used."
        ),
    }


def get_variant(variant_id: str) -> dict[str, Any]:
    for variant in capability_document()["variants"]:
        if variant["id"] == variant_id:
            return variant
    raise ValueError(f"Unknown Mage-Flow-Edit variant: {variant_id}")
