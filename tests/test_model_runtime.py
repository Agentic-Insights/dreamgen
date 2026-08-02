from types import SimpleNamespace

from src.generators.factory import resolve_image_backend
from src.services.model_runtime import ModelRuntimeManager


def runtime_config(tmp_path):
    return SimpleNamespace(
        model=SimpleNamespace(
            image_backend="auto",
            flux_model="vendor/flux",
            small_sd_model="vendor/small",
            turbo_model="vendor/turbo",
            smoke_test_model="vendor/smoke",
            mageflow_model="microsoft/Mage-Flow",
            mageflow_revision="faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9",
            mageflow_url="http://mageflow.invalid",
            zimage_model_path=tmp_path / "zimage",
            ollama_model="prompt:latest",
            ollama_image_model="",
        ),
        system=SimpleNamespace(cache_dir=tmp_path),
    )


def test_runtime_status_resolves_auto_and_reports_all_required_backends(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    monkeypatch.setattr(
        "src.services.model_runtime.resolve_image_backend",
        lambda _config, **_kwargs: "small",
    )
    monkeypatch.setattr(
        "src.services.model_runtime.probe_mageflow_runtime",
        lambda _url: {
            "ready": False,
            "status": "runtime_unavailable",
            "reason": "test runtime absent",
        },
    )
    manager = ModelRuntimeManager(config, tmp_path / "selection.json")

    payload = manager.status()

    assert payload["configured_backend"] == "auto"
    assert payload["resolved_backend"] == "small"
    assert {item["backend"] for item in payload["backends"]} >= {
        "mageflow",
        "flux",
        "small",
        "turbo",
        "zimage",
        "ollama",
        "smoke",
        "mock",
    }
    assert "system" in payload["memory"]
    assert payload["recommended"]["backend"] in {"mageflow", "zimage", "flux", "small"}


def test_runtime_requires_both_mageflow_checkpoint_and_sidecar(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    manager = ModelRuntimeManager(config, tmp_path / "selection.json")
    monkeypatch.setattr(
        manager,
        "_hf_model",
        lambda _model_id: {
            "status": "ready",
            "size": 17_507_371_519,
            "incomplete_files": 0,
            "path": "cached",
        },
    )
    monkeypatch.setattr(
        "src.services.model_runtime.probe_mageflow_runtime",
        lambda _url: {
            "ready": False,
            "status": "runtime_unavailable",
            "reason": "sidecar unavailable",
        },
    )

    status = manager._mageflow()

    assert status["status"] == "runtime_unavailable"
    assert status["reason"] == "sidecar unavailable"


def test_runtime_rejects_unverified_mageflow_revision(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    manager = ModelRuntimeManager(config, tmp_path / "selection.json")
    monkeypatch.setattr(
        manager,
        "_hf_model",
        lambda _model_id: {
            "status": "ready",
            "size": 17_507_371_519,
            "incomplete_files": 0,
            "path": "cached",
        },
    )
    monkeypatch.setattr(
        "src.services.model_runtime.probe_mageflow_runtime",
        lambda _url: {
            "ready": True,
            "status": "ready",
            "model_id": "microsoft/Mage-Flow",
            "model_revision": "unverified",
        },
    )

    status = manager._mageflow()

    assert status["status"] == "revision_mismatch"
    assert config.model.mageflow_revision in status["reason"]


def test_runtime_detects_complete_local_zimage(tmp_path):
    config = runtime_config(tmp_path)
    root = config.model.zimage_model_path
    for relative in (
        "model_index.json",
        "tokenizer/tokenizer.json",
        "vae/diffusion_pytorch_model.safetensors",
        "transformer/model.safetensors",
        "text_encoder/model.safetensors",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ready")

    status = ModelRuntimeManager(config)._local_zimage()
    assert status["status"] == "ready"
    assert status["size"] > 0


def test_auto_prefers_ready_local_zimage(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    root = config.model.zimage_model_path
    for relative in (
        "model_index.json",
        "tokenizer/tokenizer.json",
        "vae/diffusion_pytorch_model.safetensors",
        "transformer/model.safetensors",
        "text_encoder/model.safetensors",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ready")

    monkeypatch.setattr("src.generators.factory.is_model_cached", lambda _model_id: False)
    assert resolve_image_backend(config) == "zimage"


def test_unavailable_zimage_resolves_to_small_fallback(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    config.model.image_backend = "zimage"
    monkeypatch.setattr("src.generators.factory.is_model_cached", lambda _model_id: False)

    assert resolve_image_backend(config) == "small"


def test_runtime_status_explains_mageflow_fallback(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    monkeypatch.setattr(
        "src.services.model_runtime.resolve_image_backend",
        lambda _config, **_kwargs: "small",
    )
    monkeypatch.setattr(
        "src.services.model_runtime.probe_mageflow_runtime",
        lambda _url: {
            "ready": False,
            "status": "runtime_unavailable",
            "reason": "test runtime absent",
        },
    )
    manager = ModelRuntimeManager(config, tmp_path / "selection.json")

    payload = manager.status()

    assert payload["active_model"] == "Small Stable Diffusion"
    assert payload["active_model_id"] == "vendor/small"
    assert payload["preferred_model"] == "Microsoft Mage-Flow"
    assert payload["preferred_model_status"] == "not_downloaded"
    assert "Mage-Flow unavailable" in payload["fallback_reason"]


def test_runtime_selection_survives_restart(tmp_path):
    config = runtime_config(tmp_path)
    path = tmp_path / "selection.json"
    config.model.image_backend = "zimage"
    config.model.ollama_image_model = "image:latest"
    ModelRuntimeManager(config, path).persist_selection()

    restored = runtime_config(tmp_path)
    ModelRuntimeManager(restored, path).load_selection()

    assert restored.model.image_backend == "zimage"
    assert restored.model.ollama_image_model == "image:latest"
