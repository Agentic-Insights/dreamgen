# Docker Development Environment

## Quick Start

```powershell
# Start development environment
.\docker-dev-up.ps1

# Or manually:
docker-compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.docker up -d
```

## Services

- **Frontend**: http://localhost:7860 (Next.js with hot-reload)
- **Backend**: http://localhost:8001 (FastAPI with uvicorn reload)
- **API Status**: http://localhost:8001/api/status

## Development Features

### Hot Reload
- **Backend**: Python source code in `src/` is mounted, changes trigger auto-reload
- **Frontend**: Next.js dev server with Turbopack, instant updates

### Source Mounts
```yaml
Backend:
  - ./src:/app/src
  - ./data:/app/data
  - ./output:/app/output
  - ./logs:/app/logs

Frontend:
  - ./web-ui:/app (full source mount)
  - /app/node_modules (excluded)
  - /app/.next (excluded)
```

## Environment Configuration

Edit `.env.docker` to configure:
- `BACKEND_PORT=8001` (default, port 8000 conflicts with mem8)
- `USE_MOCK_GENERATOR=true` (set to false to use real GPU models)
- `MOCK_MODE=true` (set to false for real generation)

## Useful Commands

```powershell
# View logs
docker logs -f imagegen-backend
docker logs -f imagegen-frontend

# Restart a service
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart frontend

# Stop services
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down

# Rebuild and restart
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

## Mock Mode vs Real Mode

**Mock Mode** (default, no GPU required):
- `USE_MOCK_GENERATOR=true`
- `MOCK_MODE=true`
- Generates placeholder images
- Fast, no model downloads

**Real Mode** (requires GPU and models):
- `USE_MOCK_GENERATOR=false`
- `MOCK_MODE=false`
- Requires HF_TOKEN in .env
- Downloads ~15GB of models on first run
- Needs NVIDIA GPU with CUDA support

## Troubleshooting

### Backend won't start
Check logs: `docker logs imagegen-backend`
Common issues:
- Missing environment variables (see .env.docker)
- Port 8001 in use (change BACKEND_PORT)

### Frontend won't start
Check logs: `docker logs imagegen-frontend`
Common issues:
- npm dependencies issue (rebuild: `docker-compose ... up -d --build frontend`)
- Port 7860 in use

### Hot reload not working
- Backend: Check that src/ files have proper permissions
- Frontend: Try restarting the frontend service
