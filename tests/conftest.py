"""
Pytest configuration and fixtures for all tests
"""

import atexit
import os
import shutil
import tempfile

import pytest

# Create a session-scoped temp output directory at module import time so that the
# value is available before any test module sets os.environ["OUTPUT_DIR"].  Tests
# that import src.api.server at module level (like test_api.py) set their own
# temp dir; this fallback covers other test modules that rely on conftest alone.
_CONFTEST_OUTPUT_DIR = tempfile.mkdtemp(prefix="dreamgen_conftest_output_")
atexit.register(shutil.rmtree, _CONFTEST_OUTPUT_DIR, ignore_errors=True)


# Set all required environment variables before any imports
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup environment variables for all tests"""
    test_env = {
        "USE_MOCK_GENERATOR": "true",
        "MOCK_MODE": "true",
        "LORA_DIR": "./loras",
        "LORA_APPLICATION_PROBABILITY": "0.7",
        "ENABLED_LORAS": "",
        "OLLAMA_MODEL": "llama3.2:3b",
        "OLLAMA_TEMPERATURE": "0.7",
        "OLLAMA_HOST": "http://localhost:11434",
        "FLUX_MODEL": "black-forest-labs/FLUX.1-schnell",
        "MAX_SEQUENCE_LENGTH": "512",
        "IMAGE_HEIGHT": "768",
        "IMAGE_WIDTH": "1360",
        "NUM_INFERENCE_STEPS": "4",
        "GUIDANCE_SCALE": "0.0",
        "TRUE_CFG_SCALE": "1.0",
        "ENABLED_PLUGINS": "time_of_day,art_style",
        "PLUGIN_ORDER": "time_of_day:1,art_style:2",
        "OUTPUT_DIR": os.environ.get("OUTPUT_DIR", _CONFTEST_OUTPUT_DIR),
        "LOG_DIR": "./logs",
        "CACHE_DIR": "./.cache",
        "CPU_ONLY": "false",
        "MPS_USE_FP16": "false",
    }

    # Set environment variables (preserve OUTPUT_DIR if already set by a test module)
    for key, value in test_env.items():
        if key != "OUTPUT_DIR" or key not in os.environ:
            os.environ[key] = value

    yield

    # Cleanup not needed as tests run in isolated process
