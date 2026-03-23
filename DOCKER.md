# Docker Setup

This repo now uses a single simple Docker flow aimed at end users: start the stack, open the UI, generate prompts, generate images.

## Quick Start

1. Copy the example env file:
   ```bash
   cp .env.docker.example .env.docker
   ```

2. Set the values you care about in `.env.docker`:
   - `HF_TOKEN` for real model downloads
   - `IMAGE_BACKEND=auto` for the default behavior: use FLUX when cached, otherwise fall back to the tiny public smoke-test model
   - `IMAGE_BACKEND=mock` if you want placeholder images instead of real generation
   - `OLLAMA_HOST` if Ollama is not running on the same machine

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
- The tiny fallback model is public and does not require a Hugging Face token.
- If you do not have a compatible GPU and only want placeholder images, set `IMAGE_BACKEND=mock`.
