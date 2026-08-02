import json

import pytest
from PIL import Image

from src.services.edit_artifacts import append_manifest, persist_derivative, persist_source
from src.utils.gallery_publisher import build_publish_plan, build_release_manifest
from src.utils.mage_edit import capability_document
from src.utils.publication_catalog import register_image, set_edit_decision, set_publication_state


def png_bytes(tmp_path, name="source.png", color="navy"):
    path = tmp_path / name
    Image.new("RGB", (64, 48), color).save(path)
    return path.read_bytes()


def test_capabilities_use_only_official_models_and_no_strength(monkeypatch):
    for name in (
        "MAGEFLOW_EDIT_BASE_REVISION",
        "MAGEFLOW_EDIT_ALIGNED_REVISION",
        "MAGEFLOW_EDIT_TURBO_REVISION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MAGEFLOW_EDIT_ENABLED", "true")

    document = capability_document()

    assert document["official_name"] == "Mage-Flow-Edit"
    assert [item["repository"] for item in document["variants"]] == [
        "microsoft/Mage-Flow-Edit-Base",
        "microsoft/Mage-Flow-Edit",
        "microsoft/Mage-Flow-Edit-Turbo",
    ]
    assert [item["default_steps"] for item in document["variants"]] == [30, 30, 4]
    assert "strength" not in document["controls"]
    assert document["unsupported_controls"] == ["strength"]
    assert document["provenance_status"] == "official_repositories_withdrawn"
    assert document["unverified_community_repositories"] == [
        "mage-flow-community/Mage-Flow-Edit-Base",
        "mage-flow-community/Mage-Flow-Edit",
        "mage-flow-community/Mage-Flow-Edit-Turbo",
    ]
    assert all(
        not item["repository"].startswith("mage-flow-community/") for item in document["variants"]
    )
    assert "unendorsed duplicates" in document["access_note"]
    assert not document["available"]


def test_edit_artifacts_are_content_addressed_versioned_and_hash_linked(tmp_path):
    output = tmp_path / "output"
    source, source_hash = persist_source(output, "root", png_bytes(tmp_path))
    derivative_bytes = png_bytes(tmp_path, "result.png", "teal")
    derivative, derivative_hash = persist_derivative(
        output,
        "root",
        "job-one",
        1,
        derivative_bytes,
        command="make it teal",
        metadata={"source_sha256": source_hash},
    )
    first, first_hash = append_manifest(
        output, "root", "job-one", 1, {"event": "created", "derivative_sha256": derivative_hash}
    )
    second, _ = append_manifest(
        output, "root", "job-one", 1, {"event": "decision", "decision_state": "approved"}
    )

    assert source_hash[:20] in source.name
    assert derivative_hash[:20] in derivative.name
    assert json.loads(second.read_text())["previous_manifest_sha256"] == first_hash
    with pytest.raises(FileExistsError):
        persist_derivative(
            output,
            "root",
            "job-one",
            1,
            derivative_bytes,
            command="make it teal",
            metadata={"source_sha256": source_hash},
        )
    assert first.exists()


def test_cloudflare_plan_requires_explicit_edit_approval_and_preserves_lineage(tmp_path):
    output = tmp_path / "output"
    image = output / "edits" / "root" / "versions" / "v001.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (64, 64), "teal").save(image)
    image.write_bytes(image.read_bytes() + (b"deterministic-proof-padding" * 400))
    image.with_suffix(".txt").write_text("make it teal", encoding="utf-8")
    metadata = {
        "model": "microsoft/Mage-Flow-Edit-Turbo",
        "edit_lineage": {
            "role": "derivative",
            "root_job_id": "root",
            "parent_job_id": None,
            "version": 1,
            "decision_state": "pending",
        },
    }
    register_image(image, output, prompt="make it teal", metadata=metadata)

    with pytest.raises(PermissionError):
        set_publication_state(output, image.relative_to(output).as_posix(), "published")

    decision_manifest, decision_sha = append_manifest(
        output,
        "root",
        "job-one",
        1,
        {"event": "decision", "decision_state": "approved"},
    )
    set_edit_decision(
        output,
        image.relative_to(output).as_posix(),
        "approved",
        decision_manifest_path=decision_manifest.relative_to(output).as_posix(),
        decision_manifest_sha256=decision_sha,
    )
    set_publication_state(output, image.relative_to(output).as_posix(), "published")
    plan = build_publish_plan(output, since=None, limit=None)
    release = build_release_manifest(output, plan, published_at="2026-08-01T12:00:00Z")

    assert plan.image_count == 1
    assert release.manifest["items"][0]["metadata"]["edit_lineage"]["root_job_id"] == "root"
    assert release.manifest["items"][0]["metadata"]["edit_lineage"]["decision_state"] == "approved"
    assert release.manifest["schema_version"] == 2
    assert release.manifest["items"][0]["edit_lineage"]["root_job_id"] == "root"
    assert release.manifest["items"][0]["decision_manifest_sha256"] == decision_sha
    assert any(asset.reason == "immutable edit decision manifest" for asset in plan.assets)


def test_cloudflare_worker_keeps_v2_release_as_approval_boundary():
    from pathlib import Path

    worker = (
        Path(__file__).parents[1]
        / "cloudflare-gallery"
        / "functions"
        / "api"
        / "images"
        / "[[path]].js"
    ).read_text(encoding="utf-8")

    assert "value.schema_version === 1 || value.schema_version === 2" in worker
    assert "editLineage" in worker
    assert "decisionManifestUrl" in worker
