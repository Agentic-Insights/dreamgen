"""Deterministic, bounded dream-source variation for prompt generation."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEVELS = ("calm", "strange", "wild")
_MOTIFS_PATH = Path(__file__).resolve().parents[2] / "data" / "dream_source_motifs.json"


@dataclass(frozen=True)
class DreamSourceSelection:
    """One source-world mix resolved once for a generation job."""

    level: str
    seed: int | None
    motifs: dict[str, str]
    prompt: str

    def to_provenance(self) -> dict[str, Any]:
        return {
            "plugin": "dream_source_mixer",
            "category": "entropy",
            "selection_source": (
                "seeded_local_motif_bank" if self.seed is not None else "local_motif_bank"
            ),
            "seed": self.seed,
            "level": self.level,
            "motifs": dict(self.motifs),
        }


def _load_motifs() -> dict[str, list[str]]:
    with _MOTIFS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {str(key): [str(value) for value in values] for key, values in payload.items()}


def select_dream_source_mix(
    seed: int | None = None, entropy_level: str = "strange"
) -> DreamSourceSelection:
    """Select one bounded source-world mix, reproducibly when ``seed`` is provided."""
    level = str(entropy_level).strip().lower()
    if level not in LEVELS:
        raise ValueError(f"entropy_level must be one of {', '.join(LEVELS)}")
    # The requested seed remains the provenance identity. Wild mode uses a
    # deterministic offset so the same seed can intentionally explore a
    # different source-world branch than calm/strange.
    rng_seed = seed + 7919 if seed is not None and level == "wild" else seed
    rng = random.Random(rng_seed)
    motifs = _load_motifs()
    selection = {
        axis: rng.choice(options[:2] if level == "calm" else options)
        for axis, options in motifs.items()
    }
    prefix = {
        "calm": "A coherent dream fragment with gentle source-world continuity:",
        "strange": (
            "A dream fragment assembled from a surprising but legible source-world collision:"
        ),
        "wild": (
            "A volatile dream fragment where distant source-worlds collide while the subject "
            "remains readable:"
        ),
    }[level]
    prompt = (
        f"{prefix} place={selection['place']}; material={selection['material']}; "
        f"light={selection['light']}; camera={selection['camera']}; era={selection['era']}; "
        f"mood={selection['mood']}. Preserve tactile detail and visual continuity."
    )
    return DreamSourceSelection(level=level, seed=seed, motifs=selection, prompt=prompt)


def get_dream_source_mixer() -> str:
    """Legacy-compatible zero-argument plugin entry point."""
    return select_dream_source_mix().prompt
