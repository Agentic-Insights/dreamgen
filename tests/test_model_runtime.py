from types import SimpleNamespace

from src.services.model_runtime import ModelRuntimeManager


def runtime_config(tmp_path):
    return SimpleNamespace(
        model=SimpleNamespace(
            image_backend="auto",
            flux_model="vendor/flux",
            small_sd_model="vendor/small",
            turbo_model="vendor/turbo",
            smoke_test_model="vendor/smoke",
            zimage_model_path=tmp_path / "zimage",
            ollama_model="prompt:latest",
            ollama_image_model="",
        ),
        system=SimpleNamespace(cache_dir=tmp_path),
    )


def test_runtime_status_resolves_auto_and_reports_all_required_backends(tmp_path, monkeypatch):
    config = runtime_config(tmp_path)
    monkeypatch.setattr("src.services.model_runtime.resolve_image_backend", lambda _config: "small")
    manager = ModelRuntimeManager(config, tmp_path / "selection.json")

    payload = manager.status()

    assert payload["configured_backend"] == "auto"
    assert payload["resolved_backend"] == "small"
    assert {item["backend"] for item in payload["backends"]} >= {
        "flux",
        "small",
        "turbo",
        "zimage",
        "ollama",
        "smoke",
        "mock",
    }
    assert "system" in payload["memory"]
    assert payload["recommended"]["backend"] in {"zimage", "flux", "small"}


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
