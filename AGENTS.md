# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Core Commands

### Run the application
```bash
# Single image generation
uv run dreamgen generate

# Interactive mode with prompt refinement
uv run dreamgen generate --interactive

# Continuous generation loop
uv run dreamgen loop --batch-size 10 --interval 300

# Mock mode (no model downloads, placeholder images)
uv run dreamgen generate --mock
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

### Docker review quickstart
```bash
# 1. Create local Docker env
cp .env.docker.example .env.docker

# 2. Start the full stack
docker compose --env-file .env.docker up --build

# 3. Verify the running app
# UI:    http://localhost:7860
# API:   http://localhost:25800/api/status
# Model: http://localhost:25800/api/models/status

# 4. Stop the stack
docker compose --env-file .env.docker down
```

Docker notes for reviewers:
- Default path is `IMAGE_BACKEND=auto`: use Mage-Flow only when its isolated runtime
  and pinned public checkpoint are ready, then ready Z-Image-Turbo, cached FLUX,
  or the smaller public model.
- `HF_TOKEN` is optional for `auto`, `small`, `turbo`, and `smoke`; it is required if Docker needs to download gated Hugging Face models such as some FLUX variants.
- Backend runs on `25800`, frontend runs on `7860`.
- Ollama is expected on `http://host.docker.internal:11434` from inside Docker on this machine.
- If generated images look like diagnostic noise, the stack is likely on `smoke`; use `auto` or `small` for a real visual check.

### Presentation preview rule

Any DreamGen preview presented for review must come from a fresh Docker rebuild followed by
container health and affected API/UI checks. Local Next.js dev servers may be used for
development only and must not be presented as the current Docker/reviewer surface.

### Post-merge Docker deployment SOP

After a branch is merged to `main`, do not treat a local dev server as the deployed review surface. The Next.js dev server on ports such as `3000` or `3001` is only for hot-reload development. The Docker stack is the reviewer/staging-like surface:

- Frontend: `http://localhost:7860`
- Backend/API: `http://localhost:25800`

When merged changes affect `web-ui/`, frontend Dockerfiles, shared UI configuration, or any API contract consumed by the UI, rebuild and restart the Docker frontend:

```bash
docker compose --env-file .env.docker up -d --build frontend
```

When merged changes affect `src/`, backend Dockerfiles, model/runtime configuration, API behavior, generation jobs, plugins, or storage/catalog behavior, rebuild and restart the Docker backend:

```bash
docker compose --env-file .env.docker up -d --build backend
```

If changes span both sides or the affected service is ambiguous, rebuild the full stack:

```bash
docker compose --env-file .env.docker up -d --build
```

After deployment, verify the Docker surfaces, not only the dev server:

```bash
curl http://localhost:25800/api/status
curl http://localhost:25800/api/models/status
```

Then open `http://localhost:7860` and click through the affected flows. If `7860` does not reflect the merged change but `3000`/`3001` does, the Docker frontend has not been rebuilt or restarted yet.

## Architecture Overview

This is a Python-based AI image generation system with the following architecture:

### Core Components

1. **Generator System** (`src/generators/`)
   - `prompt_generator.py`: Uses Ollama to generate creative prompts with plugin context
   - `image_generator.py`: Uses Flux transformers for image generation with CUDA/MPS support
   - `zimage_generator.py`: Uses the local Z-Image-Turbo backend when configured
   - `stable_diffusion_image_generator.py`: Uses the small public Stable Diffusion fallback model
   - `turbo_image_generator.py`: Uses the fast turbo backend for low-step generation
   - `mock_image_generator.py`: Placeholder generator for testing without GPU

2. **Plugin System** (`src/plugins/`)
   - Modular architecture for prompt enhancement
   - Plugins inject context (time, holidays, art styles, Lora models) into prompts
   - Each plugin implements `get_context()` returning optional enhancement text
   - Managed by `PluginManager` with enable/disable and execution order control

3. **CLI System** (`src/utils/cli.py`)
   - Typer-based CLI with commands: generate, loop, diagnose
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

- Small public fallback models can be prefetched without a token; larger gated models still use Hugging Face tokens
- Supports both Flux dev (non-commercial) and schnell (commercial) models
- Lora models loaded from configurable directory with version detection
- Automatic GPU detection with fallback to CPU
- Memory management with cache clearing between generations
- Comprehensive error handling with retry logic
