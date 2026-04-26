# ✨ DreamGen

Generate unlimited AI images locally with no subscriptions, no cloud APIs, and complete privacy. Your machine dreams with you! ✨

![Do androids dream of electric sheep?](https://host-image.agentic.workers.dev/)

## ✨ Modern Web Interface

Beautiful, VS Code-inspired dark theme with real-time generation and organized galleries. The web interface features:

- **🎨 Smart Generation Dashboard** - AI-enhanced prompts with contextual plugins
- **🖼️ Weekly Gallery Organization** - Browse your creations by week with thumbnail previews
- **⚙️ Plugin Management** - Configure time-aware and artistic enhancement plugins
- **📊 Real-time Status** - Monitor API, GPU, and generation progress

## 🚀 Install

### Option 1: Install the CLI from PyPI

Use this path if you want to run DreamGen as an installed command and do not need to edit the source code.

```bash
uv venv --python 3.11
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
uv pip install dreamgen
```

Verify the install without downloading image models or requiring a GPU:

```bash
dreamgen generate --mock
```

The plain `uv pip install dreamgen` command resolves from PyPI. For NVIDIA systems where you specifically want CUDA 12.4 PyTorch wheels from the PyTorch index, include the extra index during install:

```bash
uv pip install dreamgen --extra-index-url https://download.pytorch.org/whl/cu124
```

### Option 2: Run from source

Use this path for development, local web UI work, or Docker review.

```bash
# Clone the repository
git clone https://github.com/Agentic-Insights/dreamgen
cd dreamgen

# Install Python dependencies
uv sync

# Configure the app
cp .env.example .env
# Edit .env for your machine:
# - OLLAMA_MODEL must point at a local Ollama model
# - OLLAMA_IMAGE_MODEL is optional and only used for IMAGE_BACKEND=ollama
# - HF_TOKEN is optional for small/turbo/smoke public models
# - IMAGE_BACKEND=auto uses FLUX if cached, otherwise the small public fallback

# Generate from the CLI
uv run dreamgen generate

# Start the API (terminal 1)
uv run uvicorn src.api.server:app --host 127.0.0.1 --port 25800

# Start the web UI (terminal 2)
cd web-ui
npm install
npm run dev
```

The local dev UI runs at `http://localhost:3000` and talks to the API at `http://localhost:25800`.

Source checkouts use `uv run dreamgen ...`. PyPI installs use `dreamgen ...`.

### Option 3: Run with Docker Compose

For a production-style local run with the shipped ports and wiring:

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

That exposes:

- UI: `http://localhost:7860`
- API: `http://localhost:25800`
- API docs: `http://localhost:25800/api/docs`

For Z-Image review in Docker:

- put LoRAs under `./loras/<name>/*.safetensors`
- use **Settings → Models** to download `Z-Image-Turbo`
- use **Settings → Models** to switch the active backend to `Z-Image`
- use **Settings → Plugins** to enable `lora` and then select active LoRAs in the Models panel

For Ollama-backed image generation:

- install at least one Ollama image model such as `x/z-image-turbo` or `x/flux2-klein`
- use **Settings → Ollama** to pick the Ollama prompt model and Ollama image model separately
- use **Settings → Models** to switch the active backend to `Ollama Image`

## 🔑 Why Choose This?

- **🏠 100% Local**: No cloud APIs, no usage limits, complete privacy
- **🧠 Smart Prompts**: AI-enhanced prompts with time, holidays, and art styles
- **🌐 Modern UI**: Professional web interface with galleries and real-time updates
- **💰 Zero Cost**: Generate unlimited images after initial setup
- **🔌 Extensible**: Plugin system for custom prompt enhancements

## 🎮 Quick Commands

These examples assume a source checkout. If you installed from PyPI, drop `uv run` and run `dreamgen ...` directly.

```bash
# Generate a single image
uv run dreamgen generate

# Generate with interactive prompt refinement
uv run dreamgen generate --interactive

# Generate multiple images in a batch
uv run dreamgen loop --batch-size 10 --interval 300

# Use mock mode (no GPU required)
uv run dreamgen generate --mock

# Force the local Z-Image backend
uv run dreamgen generate --backend zimage

# List prompt plugins
uv run dreamgen plugins list

# Get help
uv run dreamgen --help
```

## 🔧 Requirements

- **Python 3.11+** with uv package manager
- **Ollama** for prompt generation ([ollama.ai](https://ollama.ai))
- **Hugging Face Token** for gated/private model downloads only
- **GPU recommended**: NVIDIA (8GB+ VRAM) or Apple Silicon

## 📖 Full Documentation

For detailed setup, Docker usage, and development workflow:

- [docs/DOCKER.md](docs/DOCKER.md)
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)

## ☁️ Optional: Cloudflare Hosting

DreamGen includes two Cloudflare Workers for free, global image hosting:

### 1. Single Image Worker (`host-image/`)

**Purpose**: Host a single showcase image from R2 storage
**Use Case**: README badges, social media previews, landing pages

**Features**:
- Serves the most recent PNG from R2
- R2 bucket binding: `DREAM_BUCKET` → `continuous-image-gen`
- CORS enabled, 1-day cache
- Simple TypeScript worker

**Setup**:
```bash
cd host-image
npx wrangler deploy
```

**Configuration** (`wrangler.jsonc`):
```json
{
  "name": "host-image",
  "main": "src/index.ts",
  "r2_buckets": [
    { "binding": "DREAM_BUCKET", "bucket_name": "continuous-image-gen" }
  ]
}
```

### 2. Gallery API Worker (`cloudflare-gallery/`)

**Purpose**: Full gallery API with listing and image retrieval
**Use Case**: Web UI backend, public gallery, API integrations

**Features**:
- Dynamic routing via Cloudflare Pages Functions (`[[path]].js`)
- **List endpoint**: `GET /api/images` → returns sorted image keys
- **Serve endpoint**: `GET /api/images/{path}` → streams image files
- R2 bucket binding: `GALLERY` → `dreamgen-gallery`
- Auto-detects content types (png/jpg/webp/gif)
- CORS enabled, 1-year cache for images

**Setup**:
```bash
cd cloudflare-gallery
npx wrangler pages deploy public
```

**Configuration** (`wrangler.toml`):
```toml
name = "dreamgen-gallery"
pages_build_output_dir = "public"
[[r2_buckets]]
binding = "GALLERY"
bucket_name = "dreamgen-gallery"
```

**API Endpoints**:
```bash
# List all images (sorted by upload date, newest first)
curl https://your-worker.pages.dev/api/images

# Get specific image
curl https://your-worker.pages.dev/api/images/2024/week_52/image.png
```

**Key Differences**:
| Feature | host-image | cloudflare-gallery |
|---------|------------|-------------------|
| **Type** | Cloudflare Worker | Pages Function |
| **Routing** | Single endpoint | Dynamic catch-all |
| **Images** | 1 hardcoded | Full R2 listing |
| **Cache** | 1 day | 1 year |
| **Use Case** | Static showcase | Dynamic gallery API |

---

Built by [Agentic Insights](https://agenticinsights.com) • [Report Issues](https://github.com/Agentic-Insights/dreamgen/issues)
