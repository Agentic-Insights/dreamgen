from src.utils.image_engine_catalog import image_engine_catalog


def test_catalog_preserves_exact_model_identities_and_roles():
    catalog = image_engine_catalog()
    engines = {engine["id"]: engine for engine in catalog["engines"]}

    assert catalog["target_default"] == "flux2-klein-4b"
    assert catalog["benchmark_lanes"] == ["longcat-image", "qwen-image-edit-2511"]
    assert engines["flux2-klein-4b"]["repository"] == "black-forest-labs/FLUX.2-klein-4B"
    assert engines["longcat-image"]["repository"] == "meituan-longcat/LongCat-Image"
    assert engines["qwen-image-edit-2511"]["repository"] == "Qwen/Qwen-Image-Edit-2511"
    assert all(len(engine["revision"]) == 40 for engine in engines.values())
    assert all(engine["license"] == "Apache-2.0" for engine in engines.values())


def test_catalog_does_not_claim_unimplemented_backends_are_selectable():
    catalog = image_engine_catalog()

    assert catalog["target_default_selectable"] is False
    assert catalog["policy"]["no_aliasing"] is True
    assert catalog["policy"]["no_implicit_fallback"] is True
    assert all(engine["dreamgen_adapter"] is None for engine in catalog["engines"])
    assert all(engine["selectable"] is False for engine in catalog["engines"])
    assert all(engine["measured_on_target"] is False for engine in catalog["engines"])


def test_catalog_exposes_only_upstream_supported_operation_controls():
    engines = {engine["id"]: engine for engine in image_engine_catalog()["engines"]}

    klein = engines["flux2-klein-4b"]
    assert klein["operations"] == (
        "text-to-image",
        "single-reference-edit",
        "multi-reference-edit",
    )
    assert klein["defaults"]["num_inference_steps"] == 4
    assert "strength" not in klein["supported_controls"]

    longcat = engines["longcat-image"]
    assert longcat["operations"] == ("text-to-image",)

    qwen = engines["qwen-image-edit-2511"]
    assert "text-to-image" not in qwen["operations"]
    assert "strength" not in qwen["supported_controls"]
