"""
Test cases for configuration management.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.utils.config import Config


class TestConfigMissingEnv:
    """Test configuration behavior when .env file is missing or incomplete."""

    def test_missing_env_file_raises_error(self):
        """Test that missing .env file raises appropriate errors."""
        # Clear environment variables and test with non-existent file
        env_vars_to_clear = [
            "OLLAMA_MODEL",
            "OLLAMA_TEMPERATURE",
            "FLUX_MODEL",
            "MAX_SEQUENCE_LENGTH",
            "IMAGE_HEIGHT",
            "IMAGE_WIDTH",
            "NUM_INFERENCE_STEPS",
            "GUIDANCE_SCALE",
            "TRUE_CFG_SCALE",
            "LORA_DIR",
            "LORA_APPLICATION_PROBABILITY",
            "ENABLED_LORAS",
            "ENABLED_PLUGINS",
            "PLUGIN_ORDER",
            "OUTPUT_DIR",
            "LOG_DIR",
            "CACHE_DIR",
            "CPU_ONLY",
            "MPS_USE_FP16",
        ]

        original_values = {}
        for var in env_vars_to_clear:
            original_values[var] = os.environ.get(var)
            if var in os.environ:
                del os.environ[var]

        try:
            # This should raise ValueError for missing environment variables
            with pytest.raises(ValueError, match="environment variable is required"):
                Config(env_file=Path("nonexistent.env"))
        finally:
            # Restore original environment variables
            for var, value in original_values.items():
                if value is not None:
                    os.environ[var] = value

    def test_partial_env_variables_raise_specific_errors(self):
        """Test that missing specific environment variables raise appropriate errors."""
        test_cases = [
            ("OLLAMA_MODEL", "OLLAMA_MODEL environment variable is required"),
            (
                "OLLAMA_TEMPERATURE",
                "OLLAMA_TEMPERATURE environment variable is required",
            ),
            ("FLUX_MODEL", "FLUX_MODEL environment variable is required"),
            ("IMAGE_HEIGHT", "IMAGE_HEIGHT environment variable is required"),
            ("LORA_DIR", "LORA_DIR environment variable is required"),
            ("ENABLED_PLUGINS", "ENABLED_PLUGINS environment variable is required"),
            ("OUTPUT_DIR", "OUTPUT_DIR environment variable is required"),
            ("CPU_ONLY", "CPU_ONLY environment variable is required"),
        ]

        # Set all required env vars except the one being tested
        base_env = {
            "OLLAMA_MODEL": "llama3.2:3b",
            "OLLAMA_TEMPERATURE": "0.7",
            "FLUX_MODEL": "black-forest-labs/FLUX.1-schnell",
            "MAX_SEQUENCE_LENGTH": "512",
            "IMAGE_HEIGHT": "768",
            "IMAGE_WIDTH": "1360",
            "NUM_INFERENCE_STEPS": "4",
            "GUIDANCE_SCALE": "0.0",
            "TRUE_CFG_SCALE": "1.0",
            "LORA_DIR": "/tmp/loras",
            "LORA_APPLICATION_PROBABILITY": "0.7",
            "ENABLED_LORAS": "",
            "ENABLED_PLUGINS": "time_of_day,art_style",
            "PLUGIN_ORDER": "time_of_day:1,art_style:2",
            "OUTPUT_DIR": "output",
            "LOG_DIR": "logs",
            "CACHE_DIR": ".cache",
            "CPU_ONLY": "false",
            "MPS_USE_FP16": "false",
        }

        for missing_var, expected_error in test_cases:
            # Set all env vars except the missing one
            test_env = base_env.copy()
            if missing_var in test_env:
                del test_env[missing_var]

            # Clear current environment and set test environment
            original_env = dict(os.environ)
            os.environ.clear()
            os.environ.update(test_env)

            try:
                with pytest.raises(ValueError, match=expected_error):
                    Config(env_file=Path("nonexistent.env"))
            finally:
                # Restore original environment
                os.environ.clear()
                os.environ.update(original_env)


class TestConfigWorkingEnv:
    """Test configuration behavior when .env file is present and complete."""

    def test_config_loads_successfully_with_complete_env(self):
        """Test that config loads successfully when all environment variables are present."""
        # Create a temporary .env file
        env_content = """# Model Configuration
OLLAMA_MODEL=llama3.2:3b
OLLAMA_TEMPERATURE=0.8
FLUX_MODEL=black-forest-labs/FLUX.1-dev
MAX_SEQUENCE_LENGTH=256

# Image Generation Settings
IMAGE_HEIGHT=512
IMAGE_WIDTH=768
NUM_INFERENCE_STEPS=8
GUIDANCE_SCALE=1.5
TRUE_CFG_SCALE=2.0

# Lora Configuration
LORA_DIR=/tmp/test/loras
ENABLED_LORAS=style1.safetensors,style2.safetensors
LORA_APPLICATION_PROBABILITY=0.8

# Plugin Configuration
ENABLED_PLUGINS=time_of_day,art_style,lora
PLUGIN_ORDER=time_of_day:1,art_style:2,lora:3

# System Configuration
OUTPUT_DIR=test_output
LOG_DIR=test_logs
CACHE_DIR=test_cache
CPU_ONLY=true
MPS_USE_FP16=true
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / ".env"
            env_file.write_text(env_content)

            # Load config with specific env file
            config = Config(env_file=env_file)

            # Verify model configuration
            assert config.model.ollama_model == "llama3.2:3b"
            assert config.model.ollama_temperature == 0.8
            assert config.model.flux_model == "black-forest-labs/FLUX.1-dev"
            assert config.model.max_sequence_length == 256

            # Verify image configuration
            assert config.image.height == 512
            assert config.image.width == 768
            assert config.image.num_inference_steps == 8
            assert config.image.guidance_scale == 1.5
            assert config.image.true_cfg_scale == 2.0

            # Verify lora configuration (account for Windows path separators)
            assert str(config.model.lora.lora_dir).replace("\\", "/") == "/tmp/test/loras"
            assert config.model.lora.enabled_loras == [
                "style1.safetensors",
                "style2.safetensors",
            ]
            assert config.model.lora.application_probability == 0.8

            # Verify plugin configuration
            assert config.plugins.enabled_plugins == [
                "time_of_day",
                "art_style",
                "lora",
            ]
            assert config.plugins.plugin_order == {
                "time_of_day": 1,
                "art_style": 2,
                "lora": 3,
            }

            # Verify system configuration
            assert str(config.system.output_dir) == "test_output"
            assert str(config.system.log_dir) == "test_logs"
            assert str(config.system.cache_dir) == "test_cache"
            assert config.system.cpu_only is True
            assert config.system.mps_use_fp16 is True

    def test_boolean_parsing_variations(self):
        """Test that boolean environment variables are parsed correctly."""
        boolean_test_cases = [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ]

        base_env_content = """OLLAMA_MODEL=llama3.2:3b
OLLAMA_TEMPERATURE=0.7
FLUX_MODEL=black-forest-labs/FLUX.1-schnell
MAX_SEQUENCE_LENGTH=512
IMAGE_HEIGHT=768
IMAGE_WIDTH=1360
NUM_INFERENCE_STEPS=4
GUIDANCE_SCALE=1.0
TRUE_CFG_SCALE=1.0
LORA_DIR=/tmp/loras
ENABLED_LORAS=
LORA_APPLICATION_PROBABILITY=0.7
ENABLED_PLUGINS=time_of_day
PLUGIN_ORDER=time_of_day:1
OUTPUT_DIR=output
LOG_DIR=logs
CACHE_DIR=.cache
MPS_USE_FP16=false
"""

        for bool_value, expected in boolean_test_cases:
            env_content = base_env_content + f"CPU_ONLY={bool_value}"

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                env_file = temp_path / ".env"
                env_file.write_text(env_content)

                config = Config(env_file=env_file)
                assert (
                    config.system.cpu_only is expected
                ), f"Expected {expected} for input {bool_value}"

    def test_empty_enabled_loras_handled_correctly(self):
        """Test that empty ENABLED_LORAS is handled correctly."""
        env_content = """OLLAMA_MODEL=llama3.2:3b
OLLAMA_TEMPERATURE=0.7
FLUX_MODEL=black-forest-labs/FLUX.1-schnell
MAX_SEQUENCE_LENGTH=512
IMAGE_HEIGHT=768
IMAGE_WIDTH=1360
NUM_INFERENCE_STEPS=4
GUIDANCE_SCALE=1.0
TRUE_CFG_SCALE=1.0
LORA_DIR=/tmp/loras
ENABLED_LORAS=
LORA_APPLICATION_PROBABILITY=0.7
ENABLED_PLUGINS=time_of_day
PLUGIN_ORDER=time_of_day:1
OUTPUT_DIR=output
LOG_DIR=logs
CACHE_DIR=.cache
CPU_ONLY=false
MPS_USE_FP16=false
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / ".env"
            env_file.write_text(env_content)

            config = Config(env_file=env_file)
            assert config.model.lora.enabled_loras == []

    def test_validation_method_works(self):
        """Test that the validation method works with environment-loaded config."""
        env_content = """OLLAMA_MODEL=llama3.2:3b
OLLAMA_TEMPERATURE=0.7
FLUX_MODEL=black-forest-labs/FLUX.1-schnell
MAX_SEQUENCE_LENGTH=512
IMAGE_HEIGHT=768
IMAGE_WIDTH=1360
NUM_INFERENCE_STEPS=4
GUIDANCE_SCALE=1.0
TRUE_CFG_SCALE=1.0
LORA_DIR=/tmp/loras
ENABLED_LORAS=
LORA_APPLICATION_PROBABILITY=0.7
ENABLED_PLUGINS=time_of_day
PLUGIN_ORDER=time_of_day:1
OUTPUT_DIR=output
LOG_DIR=logs
CACHE_DIR=.cache
CPU_ONLY=false
MPS_USE_FP16=false
"""

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            env_file = temp_path / ".env"
            env_file.write_text(env_content)

            config = Config(env_file=env_file)
            errors = config.validate()

            # Should have no validation errors for valid config
            assert len(errors) == 0
