# Docker Setup

This repo now uses a single simple Docker flow aimed at end users: start the stack, open the UI, generate prompts, generate images.

## Quick Start

1. Copy the example env file:
   ```bash
   cp .env.docker.example .env.docker
   ```

2. Set the values you care about in `.env.docker`:
   - `HF_TOKEN` for real model downloads
   - `IMAGE_BACKEND=auto` for the default behavior: use FLUX when cached, otherwise fall back to the small public model
   - `IMAGE_BACKEND=ollama` if you want DreamGen to call Ollama's image-generation endpoint
   - `IMAGE_BACKEND=zimage` if you want to review the Z-Image path specifically
   - `IMAGE_BACKEND=qwen` if you want Qwen-Image for text-rich posters, signs, and bilingual typography
   - `IMAGE_BACKEND=small` for the usable first-run fallback
   - `IMAGE_BACKEND=turbo` for the fast few-step turbo backend
   - `IMAGE_BACKEND=smoke` only for diagnostics and smoke tests
   - `IMAGE_BACKEND=mock` if you want placeholder images instead of real generation
   - `OLLAMA_HOST` if Ollama is not running on the same machine
   - `OLLAMA_IMAGE_MODEL` if you want to pin a specific Ollama image model for `IMAGE_BACKEND=ollama`

3. Start the app:
   ```bash
   docker compose --env-file .env.docker up --build
   ```

4. Open the UI:
   - Frontend: `http://localhost:7860`
   - Backend API: `http://localhost:25800`
   - API docs: `http://localhost:25800/api/docs`

## Defaults

- Backend listens on `25800`
- Frontend listens on `7860`
- Model/cache files are stored under `./.cache`
- Z-Image checkpoints are mounted at `./ckpts`
- Local LoRAs are mounted at `./loras`
- Generated images are stored under `./output`
- Logs are stored under `./logs`

## Useful Commands

```bash
# Start in the background
docker compose --env-file .env.docker up -d --build

# Follow logs
docker compose --env-file .env.docker logs -f

# Stop the stack
docker compose --env-file .env.docker down

# Rebuild from scratch
docker compose --env-file .env.docker build --no-cache
docker compose --env-file .env.docker up -d
```

## Notes

- The frontend talks directly to the published backend port, which keeps browser routing, image URLs, and WebSocket updates simple.
- `AI_CACHE_DIR` defaults to `./.cache`, so users do not need to create a machine-specific cache folder first.
- Ollama is expected to run outside Docker by default. `host.docker.internal` is mapped for Docker Desktop and Linux host-gateway setups.
- DreamGen now resolves the prompt model and Ollama image model independently, so a stale `OLLAMA_MODEL` no longer breaks the Playground prompt button if another completion-capable model is installed.
- The small and turbo fallback models are public and do not normally require a Hugging Face token.
- Qwen-Image is public Apache-2.0, but it is much larger than the fallback models and is best treated as an opt-in quality backend.
- The smoke backend is only for diagnostics; it is not expected to produce good-looking images.
- If you do not have a compatible GPU and only want placeholder images, set `IMAGE_BACKEND=mock`.

## Reviewing Z-Image In Docker

The current Docker stack supports two Z-Image review modes:

1. **Recommended: Z-Image + LoRA via DiffSynth**
   - Start the stack.
   - In **Settings → Models**, click **Download Local Copy** for `Z-Image-Turbo`.
   - Add one or more LoRAs under `./loras/<name>/*.safetensors`.
   - In **Settings → Plugins**, enable the `lora` plugin.
   - In **Settings → Models**, switch the active backend to `Z-Image` and enable the LoRAs you want to test.

2. **Native Z-Image without LoRA**
   - This still expects a local checkout at `./ref-repos/Z-Image`, which is mounted into the backend container.
   - If no LoRA is active and that checkout is missing, native Z-Image generation will fail.

Important:
- The backend and LoRA selections made in the web UI are runtime settings. They are useful for review, but a container restart returns to the `.env.docker` defaults.
