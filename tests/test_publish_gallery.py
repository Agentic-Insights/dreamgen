import json

import pytest

from scripts.publish_gallery import discover_assets
from src.utils.gallery_publisher import build_publish_plan, build_release_manifest
from src.utils.publication_catalog import (
    backfill_catalog,
    load_catalog,
    save_catalog,
    set_publication_state,
)


def test_discover_assets_skips_mock_placeholders_and_includes_prompt(tmp_path):
    output_dir = tmp_path / "output"
    week_dir = output_dir / "2026" / "week_17"
    week_dir.mkdir(parents=True)

    real_image = week_dir / "real.png"
    real_prompt = week_dir / "real.txt"
    real_image.write_bytes(b"png")
    real_prompt.write_text("prompt", encoding="utf-8")

    mock_image = week_dir / "mock.png"
    mock_image.write_bytes(b"png")
    mock_image.with_suffix(".meta.json").write_text(
        json.dumps({"backend": "mock", "is_placeholder": True}),
        encoding="utf-8",
    )

    backfill_catalog(output_dir, default_state="published")
    assets = discover_assets(output_dir, since=None, limit=None)

    assert [asset.key for asset in assets] == [
        "2026/week_17/real.png",
        "2026/week_17/real.txt",
    ]


def test_discover_assets_limit_counts_images_not_prompts(tmp_path):
    output_dir = tmp_path / "output"
    week_dir = output_dir / "2026" / "week_17"
    week_dir.mkdir(parents=True)

    for name in ("one", "two"):
        (week_dir / f"{name}.png").write_bytes(b"png")
        (week_dir / f"{name}.txt").write_text("prompt", encoding="utf-8")

    backfill_catalog(output_dir, default_state="published")
    assets = discover_assets(output_dir, since=None, limit=1)

    assert len([asset for asset in assets if asset.path.suffix == ".png"]) == 1
    assert len(assets) == 2


def test_discover_assets_uses_publication_catalog_when_present(tmp_path):
    output_dir = tmp_path / "output"
    week_dir = output_dir / "2026" / "week_17"
    week_dir.mkdir(parents=True)

    published_image = week_dir / "published.png"
    published_image.write_bytes(b"png")
    published_image.with_suffix(".txt").write_text("published", encoding="utf-8")

    hidden_image = week_dir / "hidden.png"
    hidden_image.write_bytes(b"png")
    hidden_image.with_suffix(".txt").write_text("hidden", encoding="utf-8")

    backfill_catalog(output_dir, default_state="published")
    set_publication_state(output_dir, hidden_image.relative_to(output_dir).as_posix(), "hidden")

    assets = discover_assets(output_dir, since=None, limit=None)

    assert [asset.key for asset in assets] == [
        "2026/week_17/published.png",
        "2026/week_17/published.txt",
    ]


def test_build_publish_plan_requires_catalog(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with pytest.raises(SystemExit, match="Publication catalog is missing"):
        build_publish_plan(output_dir, since=None, limit=None)


def test_build_publish_plan_reports_reasons_and_metadata_sidecar(tmp_path):
    output_dir = tmp_path / "output"
    week_dir = output_dir / "2026" / "week_17"
    week_dir.mkdir(parents=True)

    image = week_dir / "approved.png"
    image.write_bytes(b"png")
    image.with_suffix(".txt").write_text("prompt", encoding="utf-8")
    image.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "backend": "small-sd",
                "is_placeholder": False,
                "quality_flags": ["nightly"],
            }
        ),
        encoding="utf-8",
    )

    hidden = week_dir / "hidden.png"
    hidden.write_bytes(b"png")
    hidden.with_suffix(".txt").write_text("hidden", encoding="utf-8")

    backfill_catalog(output_dir, default_state="published")
    set_publication_state(output_dir, hidden.relative_to(output_dir).as_posix(), "hidden")

    plan = build_publish_plan(output_dir, since=None, limit=None)

    assert [(asset.key, asset.reason) for asset in plan.assets] == [
        ("2026/week_17/approved.png", "state=published"),
        ("2026/week_17/approved.txt", "prompt sidecar"),
        ("2026/week_17/approved.meta.json", "metadata sidecar"),
    ]
    assert plan.image_count == 1
    assert plan.delete_count == 0
    assert any(
        skipped.key.endswith("hidden.png") and skipped.reason == "state=hidden"
        for skipped in plan.skipped
    )


def test_release_manifest_is_approved_ordered_versioned_and_rollback_safe(tmp_path):
    output_dir = tmp_path / "output"
    week_dir = output_dir / "2026" / "week_31"
    week_dir.mkdir(parents=True)

    older = week_dir / "image_20260731_120000_older.png"
    newer = week_dir / "image_20260731_130000_newer.png"
    draft = week_dir / "image_20260731_140000_draft.png"
    older.write_bytes(b"older approved image")
    newer.write_bytes(b"newer approved image")
    draft.write_bytes(b"unapproved image")
    for image in (older, newer, draft):
        image.with_suffix(".txt").write_text(image.stem, encoding="utf-8")

    backfill_catalog(output_dir, default_state="published")
    set_publication_state(output_dir, draft.relative_to(output_dir).as_posix(), "draft")
    catalog = load_catalog(output_dir)
    catalog["assets"][older.relative_to(output_dir).as_posix()][
        "created_at"
    ] = "2026-07-31T12:00:00Z"
    catalog["assets"][newer.relative_to(output_dir).as_posix()][
        "created_at"
    ] = "2026-07-31T13:00:00Z"
    save_catalog(output_dir, catalog)

    plan = build_publish_plan(output_dir, since=None, limit=None)
    release = build_release_manifest(
        output_dir,
        plan,
        published_at="2026-07-31T22:00:00Z",
        previous_release={
            "release_id": "previous-release",
            "release_key": "_dreamgen/releases/previous-release.json",
        },
    )

    assert [item["key"] for item in release.manifest["items"]] == [
        "2026/week_31/image_20260731_130000_newer.png",
        "2026/week_31/image_20260731_120000_older.png",
    ]
    assert release.manifest["leading_key"].endswith("newer.png")
    assert release.manifest["image_count"] == 2
    assert (
        release.manifest["items"][0]["asset_version"]
        != release.manifest["items"][1]["asset_version"]
    )
    assert release.manifest["items"][0]["caption_version"]
    assert release.manifest["rollback"] == {
        "previous_release_id": "previous-release",
        "previous_release_key": "_dreamgen/releases/previous-release.json",
    }
    assert all("draft" not in item["key"] for item in release.manifest["items"])
    assert release.release_key.startswith("_dreamgen/releases/20260731-")

    repeated = build_release_manifest(
        output_dir,
        plan,
        published_at="2026-07-31T22:00:00Z",
        previous_release={"release_id": "previous-release"},
    )
    assert repeated.release_id == release.release_id


def test_publication_state_records_approval_and_rollback_history(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    image = output_dir / "candidate.png"
    image.write_bytes(b"creative candidate")
    image.with_suffix(".meta.json").write_text(
        json.dumps({"quality_flags": ["draft", "provisional", "nightly"]}),
        encoding="utf-8",
    )
    backfill_catalog(output_dir, default_state="draft")

    published = set_publication_state(output_dir, "candidate.png", "published")
    hidden = set_publication_state(output_dir, "candidate.png", "hidden")

    assert published["published_at"]
    assert published["quality_flags"] == ["nightly"]
    assert hidden["published_at"] == published["published_at"]
    assert hidden["unpublished_at"]
    assert hidden["publication_history"][-2]["to"] == "published"
    assert hidden["publication_history"][-1]["to"] == "hidden"
