# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Commands

```bash
# Single image generation
uv run dreamgen generate

# Interactive mode with prompt refinement
uv run dreamgen generate --interactive

# Continuous generation loop
uv run dreamgen loop --batch-size 10 --interval 300

# Mock mode (no GPU/model downloads, placeholder images)
uv run dreamgen generate --mock

# System diagnostics
uv run dreamgen diagnose

# Plugin management
uv run dreamgen plugins list              # Show all plugins
uv run dreamgen plugins enable <name>     # Enable a plugin
uv run dreamgen plugins disable <name>    # Disable a plugin
```

### Development
```bash
uv run pytest tests/                        # Run all tests
uv run pytest tests/test_mock_generator.py  # Single test file
uv run black src/ tests/                    # Format code
uv run isort src/ tests/                    # Sort imports
uv sync                                     # Install dependencies
```

### Docker - Production
```bash
docker-compose up                           # Full stack (backend + frontend in containers)
docker-compose up backend                   # API only (mock mode by default)
```

### Docker - Development Mode
For local development with GPU access, run the backend locally and frontend in Docker:

```bash
# Terminal 1: Local backend with GPU + hot reload
just dev-backend
# or: uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend container pointing to local backend
just dev-frontend
# or: docker-compose -f docker-compose.yml -f docker-compose.dev.yml up frontend
```

**Why this setup?**
- Backend runs locally with direct GPU access (CUDA) and your HuggingFace model cache
- Frontend runs in Docker for consistent Node.js environment
- Frontend connects to `host.docker.internal:8000` to reach local backend
- Hot reload enabled for both backend (uvicorn --reload) and frontend (next dev)

**Ports:**
- Backend API: `http://localhost:8000`
- Frontend: `http://localhost:22023`

## Architecture

### Data Flow
```
CLI Command → Config (.env) → Plugin System → Prompt Generator (Ollama) → Image Generator (Flux) → Storage (output/YYYY/week_XX/)
```

### Core Components

**Generators** (`src/generators/`)
- `prompt_generator.py` - Ollama chat for creative prompts, integrates plugin context
- `image_generator.py` - Flux diffusion pipeline with GPU memory management
- `mock_image_generator.py` - Placeholder for testing without GPU

**Plugin System** (`src/plugins/`)
- `PluginManager` orchestrates execution order via `PLUGIN_ORDER` env var
- Each plugin returns `PluginResult(name, value, description)`
- Built-in: `time_of_day`, `nearest_holiday`, `holiday_fact`, `art_style`, `lora`
- Art styles loaded from `data/art_styles.json`, holidays from `data/holidays.json`

**Configuration** (`src/utils/config.py`)
- Dataclass-based with nested categories: `PluginConfig`, `ModelConfig`, `ImageConfig`, `SystemConfig`, `LoraConfig`
- Requires `.env` file (copy from `.env.example`)
- Key vars: `OLLAMA_MODEL`, `FLUX_MODEL`, `ENABLED_PLUGINS`, `PLUGIN_ORDER`

**API** (`src/api/server.py`)
- FastAPI with WebSocket for real-time generation updates
- REST endpoints for gallery and generation control

**Web UI** (`web-ui/`)
- Next.js 15 + React 19 + Tailwind CSS
- Gallery organized by week, real-time status via WebSocket

### Key Patterns

- All generation is async (`async def`) with retry decorators (`@handle_errors`)
- GPU memory aggressively cleared between generations (`torch.cuda.empty_cache()`, `gc.collect()`)
- RTX 4090 optimizations in `image_generator.py` (attention slicing, VAE tiling)
- Storage: `output/YYYY/week_XX/image_YYYYMMDD_HHMMSS_<hash>.png` + `.txt` prompt file

### Flux Models
- **schnell**: 4 inference steps, commercial-friendly, faster
- **dev**: 50 steps, non-commercial, higher quality

### Environment Variables (required in `.env`)
```
OLLAMA_MODEL=qwen3-coder:30b
FLUX_MODEL=black-forest-labs/FLUX.1-schnell
ENABLED_PLUGINS=time_of_day,nearest_holiday,holiday_fact,art_style,lora
PLUGIN_ORDER=time_of_day:1,nearest_holiday:2,holiday_fact:3,art_style:4,lora:5
```
