# Docker Setup for Continuous Image Generator

This guide explains how to run the Continuous Image Generator using Docker.

## Quick Start

1. **Copy environment configuration:**
   ```bash
   cp .env.docker .env
   ```

2. **Edit `.env` file** and set your configuration:
   - Set `HF_TOKEN` if using real Flux models
   - Adjust `USE_MOCK_GENERATOR` based on GPU availability
   - Configure Ollama endpoint if available

3. **Build and run with Docker Compose:**
   ```bash
   # Production mode
   docker-compose up --build

   # Development mode with hot-reload
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
   ```

4. **Access the application:**
   - Frontend: http://localhost:7860
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

## Configuration

### Mock Mode vs Production Mode

**Mock Mode (Default):**
- No GPU required
- No model downloads needed
- Generates placeholder images
- Fast startup
- Ideal for development and testing

**Production Mode:**
- Requires GPU (NVIDIA CUDA or Apple MPS)
- Downloads Flux models (~15GB on first run)
- Generates real AI images
- Set `USE_MOCK_GENERATOR=false` in `.env`

### Volume Mounts

The Docker setup uses several volume mounts:

1. **Model Cache** (Read-only):
   - Mounts `~/.cache/huggingface` from host
   - Avoids re-downloading models
   - Saves ~15GB bandwidth

2. **Output Directory**:
   - Mounts `./output` for generated images
   - Persists across container restarts

3. **Development Mounts** (dev mode only):
   - Source code for hot-reload
   - Logs directory

### Using Existing Flux Models

If you've already downloaded Flux models locally:

1. Models are typically stored in:
   - Windows: `%USERPROFILE%\.cache\huggingface`
   - Linux/Mac: `~/.cache/huggingface`

2. The Docker setup automatically mounts this directory
3. No re-download needed!

## Docker Commands

### Build Images

```bash
# Build both services
docker-compose build

# Build specific service
docker-compose build backend
docker-compose build frontend
```

### Run Services

```bash
# Start all services
docker-compose up

# Start in background
docker-compose up -d

# Start specific service
docker-compose up backend

# View logs
docker-compose logs -f
docker-compose logs -f backend
```

### Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### Development Mode

```bash
# Run with hot-reload
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Rebuild after dependency changes
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## GPU Support

### NVIDIA GPUs (Linux/Windows WSL2)

1. Install NVIDIA Container Toolkit
2. Add to docker-compose.yml:
   ```yaml
   backend:
     deploy:
       resources:
         reservations:
           devices:
             - driver: nvidia
               count: 1
               capabilities: [gpu]
   ```

### Apple Silicon (MPS)

MPS support works automatically when running on macOS with Apple Silicon.

## Troubleshooting

### Backend won't start

Check logs:
```bash
docker-compose logs backend
```

Common issues:
- Missing HF_TOKEN for model downloads
- Insufficient disk space for models
- Port 8000 already in use

### Frontend can't connect to backend

- Ensure both services are running
- Check network connectivity:
  ```bash
  docker-compose exec frontend ping backend
  ```
- Verify API endpoint in browser: http://localhost:8000/api/status

### Out of memory errors

- Use mock mode: `USE_MOCK_GENERATOR=true`
- Reduce batch size in configuration
- Allocate more memory to Docker

### Models downloading every time

Ensure volume mount is correct:
- Windows: Check `%USERPROFILE%\.cache\huggingface` exists
- Linux/Mac: Check `~/.cache/huggingface` exists
- Verify mount in container:
  ```bash
  docker-compose exec backend ls -la /app/models
  ```

## CSO Module Deployment

This Docker setup is designed to be compatible with CloudStack Orchestrator deployment:

1. Production images are optimized for Kubernetes
2. Configuration follows CSO module patterns
3. Resource limits match CSO specifications
4. Security best practices implemented

For CSO deployment, see `cso-deployment/README.md`.

## Security Notes

- Containers run as non-root user (UID 1000/1001)
- Read-only root filesystem where possible
- Secrets should be provided via environment variables
- Never commit `.env` file with real tokens

## Performance Optimization

- Multi-stage builds reduce image size
- Model cache prevents redundant downloads
- Standalone Next.js build for production
- Health checks ensure service availability

## Additional Services

### Ollama (Optional)

To run Ollama in Docker:
```bash
# Uncomment ollama service in docker-compose.yml
docker-compose up ollama
```

### Database (Future)

PostgreSQL support is prepared for future features:
- Generation history
- User management
- Analytics

## Links

- [Backend API Docs](http://localhost:8000/docs)
- [Frontend](http://localhost:7860)
- [Health Check](http://localhost:8000/api/status)
- [Metrics](http://localhost:8000/metrics) (when enabled)
