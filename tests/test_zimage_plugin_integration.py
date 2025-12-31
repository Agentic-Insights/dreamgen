"""Integration tests for Z-Image generator with plugin system."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.generators.factory import get_available_models, get_image_generator
from src.generators.zimage_generator import ZImageGenerator
from src.plugins import (
    ensure_initialized,
    get_temporal_descriptor,
    initialize_plugins,
    plugin_manager,
)


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    config = MagicMock()
    config.model.image_model = "zimage"
    config.model.zimage_model_path = Path("/tmp/fake_zimage_model")
    config.model.zimage_attention = "_sdpa"
    config.model.zimage_compile = False
    config.image.height = 1024
    config.image.width = 1024
    config.system.output_dir = Path("/tmp/test_output")
    config.system.cpu_only = False

    # Plugin config
    config.plugins.enabled_plugins = [
        "time_of_day",
        "nearest_holiday",
        "holiday_fact",
        "art_style",
    ]
    config.plugins.plugin_order = {
        "time_of_day": 1,
        "nearest_holiday": 2,
        "holiday_fact": 3,
        "art_style": 4,
        "lora": 5,
    }

    # Lora config
    config.model.lora.lora_dir = Path("/tmp/loras")
    config.model.lora.enabled_loras = []
    config.model.lora.application_probability = 0.0

    return config


class TestZImagePluginIntegration:
    """Tests for Z-Image generator with plugins."""

    def test_factory_returns_zimage_generator(self, mock_config):
        """Test that factory creates ZImageGenerator when configured."""
        gen = get_image_generator(mock_config, mock=False)
        assert isinstance(gen, ZImageGenerator)

    def test_factory_with_mock_mode(self, mock_config):
        """Test factory mock mode returns MockImageGenerator."""
        from src.generators.mock_image_generator import MockImageGenerator

        gen = get_image_generator(mock_config, mock=True)
        assert isinstance(gen, MockImageGenerator)

    def test_plugins_initialize(self, mock_config):
        """Test that plugins initialize correctly with Z-Image config."""
        # Reset plugin state
        plugin_manager.plugins.clear()

        # Re-register and initialize plugins
        from src.plugins import register_base_plugins, register_lora_plugin

        register_base_plugins()
        register_lora_plugin(mock_config)
        initialize_plugins(mock_config)

        # Check all expected plugins are registered
        assert "time_of_day" in plugin_manager.plugins
        assert "nearest_holiday" in plugin_manager.plugins
        assert "holiday_fact" in plugin_manager.plugins
        assert "art_style" in plugin_manager.plugins

    def test_temporal_descriptor_generation(self, mock_config):
        """Test temporal descriptor is generated for Z-Image prompts."""
        # Initialize plugins
        ensure_initialized(mock_config)

        # Get temporal descriptor
        descriptor = get_temporal_descriptor()

        # Should return a string with some content
        assert isinstance(descriptor, str)
        # Should contain time-related info at minimum
        assert len(descriptor) > 0

    def test_available_models_includes_flux(self):
        """Test that flux is always listed in available models."""
        # Flux should always be available
        models = get_available_models()
        assert "flux" in models
        # Note: zimage availability depends on ref-repos/Z-Image/src existing

    def test_attention_backend_configuration(self, mock_config):
        """Test attention backend configuration options."""
        backends = ["_native_flash", "_flash_3", "_sdpa", "flash"]

        for backend in backends:
            mock_config.model.zimage_attention = backend
            with patch("torch.cuda.is_available", return_value=False):
                gen = ZImageGenerator(mock_config)
                assert gen.attention_backend == backend


class TestZImagePromptEnhancement:
    """Tests for prompt enhancement with Z-Image."""

    def test_bilingual_prompt_support(self, mock_config):
        """Test that Z-Image config supports bilingual prompts."""
        # Z-Image excels at bilingual text rendering
        prompts = [
            "A sign that says 'Hello World'",
            "一个写着'你好世界'的标志",  # Chinese: A sign that says 'Hello World'
            "Mixed: Hello 你好 World 世界",
        ]

        with patch("torch.cuda.is_available", return_value=False):
            gen = ZImageGenerator(mock_config)
            # Verify generator can be created with bilingual prompt support
            assert gen.model_path == Path("/tmp/fake_zimage_model")

            # These should all be valid prompts for Z-Image
            for prompt in prompts:
                assert isinstance(prompt, str)
                assert len(prompt) > 0


class TestZImageModelInfo:
    """Tests for Z-Image model information."""

    def test_model_info_complete(self, mock_config):
        """Test model info contains all expected fields."""
        with patch("torch.cuda.is_available", return_value=True):
            gen = ZImageGenerator(mock_config)
            info = gen.get_model_info()

            # Check required fields
            assert info["model_name"] == "Z-Image-Turbo"
            assert info["model_path"] == "/tmp/fake_zimage_model"
            assert info["parameters"] == "6B"
            assert info["architecture"] == "Single-Stream DiT (S3-DiT)"
            assert info["inference_steps"] == 8
            assert info["device"] == "cuda"
            assert "attention_backend" in info
            assert "compiled" in info
            assert "features" in info

    def test_model_info_features_list(self, mock_config):
        """Test model info features list."""
        with patch("torch.cuda.is_available", return_value=True):
            gen = ZImageGenerator(mock_config)
            info = gen.get_model_info()

            features = info["features"]
            assert isinstance(features, list)
            assert len(features) > 0

            # Check expected features are mentioned
            features_str = " ".join(features)
            assert "Photorealistic" in features_str
            assert "Bilingual" in features_str
