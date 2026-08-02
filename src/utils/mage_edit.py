"""Truthful capability and availability contract for Microsoft Mage-Flow-Edit."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

OFFICIAL_SOURCE_REPOSITORY = "https://github.com/microsoft/Mage"
OFFICIAL_SOURCE_REVISION = "6cefeb40e4c8ecc404ecb73732a91878939f27e0"
OFFICIAL_LICENSE = "MIT"
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
    repository: str
    default_steps: int
    default_guidance: float
    revision_env: str

    def descriptor(self) -> dict[str, Any]:
        revision = os.environ.get(self.revision_env, "").strip().lower()
        verified_revision = revision if FULL_SHA.fullmatch(revision) else None
        enabled = os.getenv("MAGEFLOW_EDIT_ENABLED", "false").lower() == "true"
        available = bool(enabled and verified_revision)
        return {
            **asdict(self),
            "verified_revision": verified_revision,
            "available": available,
            "availability_reason": (
                None
                if available
                else "Official checkpoint access and a verified full revision are required."
            ),
        }


VARIANTS = (
    MageEditVariant(
        id="base",
        label="Base",
        repository="microsoft/Mage-Flow-Edit-Base",
        default_steps=30,
        default_guidance=5.0,
        revision_env="MAGEFLOW_EDIT_BASE_REVISION",
    ),
    MageEditVariant(
        id="aligned",
        label="Aligned",
        repository="microsoft/Mage-Flow-Edit",
        default_steps=30,
        default_guidance=5.0,
        revision_env="MAGEFLOW_EDIT_ALIGNED_REVISION",
    ),
    MageEditVariant(
        id="turbo",
        label="Turbo",
        repository="microsoft/Mage-Flow-Edit-Turbo",
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
        "target_hardware": "NVIDIA RTX 4090-class GPU with 24 GB VRAM or better",
        "model_loaded": False,
        "queue_depth": 0,
        "gpu": {"available": False, "name": None, "vram_total_mb": None, "vram_free_mb": None},
        "controls": {
            "command": {"type": "string", "required": True},
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
        "provenance_status": "official_repositories_withdrawn",
        "unverified_community_repositories": list(UNVERIFIED_COMMUNITY_REPOSITORIES),
        "access_note": (
            "The official Microsoft Hugging Face repositories currently return 404 in a "
            "signed-in session rather than presenting a standard access agreement. Public "
            "mage-flow-community copies are unendorsed duplicates: Microsoft's current source "
            "still names only the withdrawn Microsoft repositories. DreamGen will not present "
            "those copies or another checkpoint as official Mage-Flow-Edit."
        ),
    }


def get_variant(variant_id: str) -> dict[str, Any]:
    for variant in capability_document()["variants"]:
        if variant["id"] == variant_id:
            return variant
    raise ValueError(f"Unknown Mage-Flow-Edit variant: {variant_id}")
