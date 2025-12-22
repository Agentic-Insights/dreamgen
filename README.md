# ✨ DreamGen

Generate unlimited AI images locally with no subscriptions, no cloud APIs, and complete privacy. Your machine dreams with you! ✨

![Do androids dream of electric sheep?](https://host-image.agentic.workers.dev/)

## ✨ Modern Web Interface

Beautiful, VS Code-inspired dark theme with real-time generation and organized galleries. The web interface features:

- **🎨 Smart Generation Dashboard** - AI-enhanced prompts with contextual plugins
- **🖼️ Weekly Gallery Organization** - Browse your creations by week with thumbnail previews
- **⚙️ Plugin Management** - Configure time-aware and artistic enhancement plugins
- **📊 Real-time Status** - Monitor API, GPU, and generation progress

## 🚀 Quick Install

```bash
# Install the CLI tool
uv tool install dreamgen

# Clone for web interface (optional)
git clone https://github.com/killerapp/dreamgen
cd dreamgen/web-ui && npm install

# Set up your environment
export HUGGINGFACE_TOKEN=your_token_here

# Start generating images!
dreamgen generate

# Launch the web interface
npm run dev
```

## 🔑 Why Choose This?

- **🏠 100% Local**: No cloud APIs, no usage limits, complete privacy
- **🧠 Smart Prompts**: AI-enhanced prompts with time, holidays, and art styles
- **🌐 Modern UI**: Professional web interface with galleries and real-time updates
- **💰 Zero Cost**: Generate unlimited images after initial setup
- **🔌 Extensible**: Plugin system for custom prompt enhancements

## 🎮 Quick Commands

```bash
# Generate a single image
dreamgen generate

# Generate with interactive prompt refinement
dreamgen generate --interactive

# Generate multiple images in a batch
dreamgen loop --batch-size 10 --interval 300

# Use mock mode (no GPU required)
dreamgen generate --mock

# Get help
dreamgen --help
```

## 🔧 Requirements

- **Python 3.11+** with uv package manager
- **Ollama** for prompt generation ([ollama.ai](https://ollama.ai))
- **Hugging Face Token** for model access
- **GPU recommended**: NVIDIA (8GB+ VRAM) or Apple Silicon

## 📖 Full Documentation

For detailed setup, plugin development, and advanced usage, see [CONTRIBUTING.md](CONTRIBUTING.md).

## ☁️ Optional: Cloudflare Hosting

DreamGen includes two Cloudflare Workers for free, global image hosting:

### 1. Single Image Worker (`host-image/`)

**Purpose**: Host a single showcase image from R2 storage
**Use Case**: README badges, social media previews, landing pages

**Features**:
- Serves one hardcoded image (`ComfyUI_00372_.png`)
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

Built by [Agentic Insights](https://agenticinsights.com) • [Report Issues](https://github.com/killerapp/dreamgen/issues)
