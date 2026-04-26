import json

from scripts.publish_gallery import discover_assets


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

    assets = discover_assets(output_dir, since=None, limit=1)

    assert len([asset for asset in assets if asset.path.suffix == ".png"]) == 1
    assert len(assets) == 2
