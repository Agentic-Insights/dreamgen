"""Regression tests for backend factory import behavior."""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock


def make_config(image_backend: str = "small"):
    config = MagicMock()
    config.model.image_backend = image_backend
    config.model.flux_model = "black-forest-labs/FLUX.1-schnell"
    config.model.small_sd_model = "segmind/tiny-sd"
    config.model.smoke_test_model = "hf-internal-testing/tiny-stable-diffusion-torch"
    config.model.turbo_model = "stabilityai/sd-turbo"
    config.model.zimage_model_path = Path("/tmp/fake_zimage_model")
    config.model.zimage_attention = "_sdpa"
    config.model.zimage_compile = False
    config.image.height = 1024
    config.image.width = 1024
    config.image.num_inference_steps = 4
    config.image.guidance_scale = 0.0
    config.system.output_dir = Path("/tmp/test_output")
    config.system.cpu_only = True
    return config


def test_factory_import_does_not_require_turbo_backend(monkeypatch):
    """Importing the factory for a non-turbo backend should not import turbo code."""
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.endswith("turbo_image_generator"):
            raise ImportError("turbo backend intentionally unavailable in this test")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    sys.modules.pop("src.generators.factory", None)
    sys.modules.pop("src.generators.turbo_image_generator", None)

    factory = importlib.import_module("src.generators.factory")
    generator, backend_name = factory.create_image_generator(make_config("small"))

    assert generator.backend_name == "small"
    assert backend_name == "small-sd"


def test_factory_only_imports_turbo_when_requested(monkeypatch):
    """The turbo backend should still surface import errors when explicitly requested."""
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.endswith("turbo_image_generator"):
            raise ImportError("turbo backend intentionally unavailable in this test")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    sys.modules.pop("src.generators.factory", None)
    sys.modules.pop("src.generators.turbo_image_generator", None)

    factory = importlib.import_module("src.generators.factory")

    try:
        factory.create_image_generator(make_config("turbo"))
    except ImportError as exc:
        assert "turbo backend intentionally unavailable" in str(exc)
    else:
        raise AssertionError("Expected turbo backend import to fail when explicitly requested")
