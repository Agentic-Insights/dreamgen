# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Core Commands

### Run the application
```bash
# Single image generation
uv run imagegen generate

# Interactive mode with prompt refinement
uv run imagegen generate --interactive

# Continuous generation loop
uv run imagegen loop --batch-size 10 --interval 300

# Mock mode (no model downloads, placeholder images)
uv run imagegen generate --mock

# Launch web UI (Next.js interface)
uv run imagegen web --mock
```

### Development and testing
```bash
# Run tests
uv run pytest tests/

# Run specific test
uv run pytest tests/test_mock_generator.py

# Format code
uv run black src/ tests/
uv run isort src/ tests/

# Lint code
uv run pylint src/

# Install/sync dependencies
uv sync
```

## Architecture Overview

This is a Python-based AI image generation system with the following architecture:

### Core Components

1. **Generator System** (`src/generators/`)
   - `prompt_generator.py`: Uses Ollama to generate creative prompts with plugin context
   - `image_generator.py`: Uses Flux transformers for image generation with CUDA/MPS support
   - `tiny_image_generator.py`: Uses a tiny Stable Diffusion checkpoint as a smoke-test fallback
   - `mock_image_generator.py`: Placeholder generator for testing without GPU

2. **Plugin System** (`src/plugins/`)
   - Modular architecture for prompt enhancement
   - Plugins inject context (time, holidays, art styles, Lora models) into prompts
   - Each plugin implements `get_context()` returning optional enhancement text
   - Managed by `PluginManager` with enable/disable and execution order control

3. **CLI System** (`src/utils/cli.py`)
   - Typer-based CLI with commands: generate, loop, diagnose, web
   - Rich console output with progress bars and formatted panels
   - Interactive mode for prompt refinement

4. **Configuration** (`src/utils/config.py`)
   - Dataclass-based configuration with nested categories
   - Environment variable support with fallbacks
   - Supports .env files and JSON config files

5. **Storage** (`src/utils/storage.py`)
   - Organizes output by year/week folders
   - Saves both images and prompt text files
   - Automatic directory creation
   - eventually should be in an S3 resource managed by orchestr8 platform

### Key Design Patterns

- **Async/await** for concurrent operations (image generation, Ollama calls)
- **Plugin architecture** for extensible prompt enhancement / entropy
- **Dataclass configuration** for type-safe settings
- **Rich CLI** with progress tracking and formatted output

### Technology Stack

- **Flux by Black Forrest Labs** for image generation (dev/schnell models
- **Ollama** for local LLM prompt generation
- **PyTorch** with CUDA (NVIDIA) and MPS (Apple Silicon) support
- **Next.js** for web UI
- **Docker** Containerization for K8ss / Orchestr8 / Docker compose for tessting

### Important Implementation Details

- Tiny public fallback model can be prefetched without a token; larger gated models still use Hugging Face tokens
- Supports both Flux dev (non-commercial) and schnell (commercial) models
- Lora models loaded from configurable directory with version detection
- Automatic GPU detection with fallback to CPU
- Memory management with cache clearing between generations
- Comprehensive error handling with retry logic
