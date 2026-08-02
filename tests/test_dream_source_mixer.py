"""Tests for bounded and reproducible Dream Source Mixer selection."""

from src.plugins.dream_source_mixer import select_dream_source_mix


def test_dream_source_mixer_is_deterministic_for_seed():
    first = select_dream_source_mix(seed=42, entropy_level="strange")
    second = select_dream_source_mix(seed=42, entropy_level="strange")

    assert first == second
    assert first.to_provenance()["category"] == "entropy"
    assert first.to_provenance()["seed"] == 42
    assert set(first.motifs) == {"place", "material", "light", "camera", "era", "mood"}


def test_dream_source_mixer_exposes_calm_strange_wild_levels():
    selections = [
        select_dream_source_mix(seed=7, entropy_level=level)
        for level in ("calm", "strange", "wild")
    ]

    assert [selection.level for selection in selections] == ["calm", "strange", "wild"]
    assert all("dream fragment" in selection.prompt for selection in selections)


def test_dream_source_mixer_rejects_unknown_level():
    try:
        select_dream_source_mix(seed=1, entropy_level="unknown")
    except ValueError as exc:
        assert "entropy_level" in str(exc)
    else:
        raise AssertionError("invalid entropy levels must fail closed")
