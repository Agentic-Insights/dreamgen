# DreamGen - AI Image Generation
# Streamlined automation for generation, deployment, and sync

default:
    @just --list

# =============================================================================
# Core Generation
# =============================================================================

# Generate a single image
gen:
    uv run dreamgen generate

# Generate with interactive mode
geni:
    uv run dreamgen generate --interactive

# Continuous generation loop
loop batch_size="10" interval="300":
    uv run dreamgen loop --batch-size {{batch_size}} --interval {{interval}}

# Mock mode (no GPU)
mock:
    uv run dreamgen generate --mock

# System diagnostics
diag:
    uv run dreamgen diagnose

# =============================================================================
# Plugin Management
# =============================================================================

# List all plugins
pl:
    uv run dreamgen plugins list

# Enable a plugin
pe name:
    uv run dreamgen plugins enable {{name}}

# Disable a plugin
pd name:
    uv run dreamgen plugins disable {{name}}

# =============================================================================
# Development
# =============================================================================

# Install dependencies
install:
    uv sync

# Run tests
test:
    uv run pytest tests/

# Benchmark FLUX vs Z-Image models
benchmark:
    uv run scripts/benchmark_models.py

# Benchmark specific model
benchmark-model model:
    uv run scripts/benchmark_models.py --models {{model}}

# Generate with Z-Image
gen-zimage prompt="":
    #!/usr/bin/env bash
    if [ -z "{{prompt}}" ]; then
        uv run dreamgen generate --model zimage
    else
        uv run dreamgen generate --model zimage -p "{{prompt}}"
    fi

# Run tests with coverage
test-cov:
    uv run pytest tests/ --cov=src --cov-report=html --cov-report=term

# Format code (black + isort)
fmt:
    uv run black src/ tests/
    uv run isort src/ tests/

# Lint Python code
lint:
    uv run pylint src/

# Lint Python - errors only (fast)
lint-errors:
    uv run pylint src/ --errors-only

# Type check Python code
typecheck:
    uv run mypy src/

# Lint web UI
web-lint:
    cd web-ui && npm run lint

# Fix web UI linting issues
web-lint-fix:
    cd web-ui && npm run lint -- --fix

# Run all code quality checks
check: fmt lint-errors test
    @echo "✓ All checks passed!"

# Run comprehensive checks (CI-style)
check-all: fmt lint typecheck test web-lint
    @echo "✓ All comprehensive checks passed!"

# Run sanity checks (environment, config, dependencies)
sanity:
    ./sanity-check.sh

# Setup and run pre-commit hooks
hooks-install:
    uv run pre-commit install
    @echo "✓ Pre-commit hooks installed"

# Run pre-commit on all files
hooks-run:
    uv run pre-commit run --all-files

# Update pre-commit hook versions
hooks-update:
    uv run pre-commit autoupdate

# =============================================================================
# Docker
# =============================================================================

# Start full stack (production - backend + frontend in containers)
up:
    docker-compose up

# Start in background
upd:
    docker-compose up -d

# Stop services
down:
    docker-compose down

# Rebuild containers
rebuild:
    docker-compose build

# View logs (optional service name)
logs service="":
    #!/usr/bin/env bash
    if [ -z "{{service}}" ]; then
        docker-compose logs -f
    else
        docker-compose logs -f {{service}}
    fi

# =============================================================================
# Development Mode
# =============================================================================

# Start local backend with hot reload (GPU enabled)
dev-backend:
    uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

# Start frontend container pointing to local backend
dev-frontend:
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --no-deps frontend

# Start dev frontend in background
dev-frontend-d:
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --no-deps frontend

# Full dev mode: local backend + containerized frontend
dev:
    @echo "Starting development environment..."
    @echo "  Backend: http://localhost:8000 (local, GPU enabled)"
    @echo "  Frontend: http://localhost:22023 (containerized)"
    @echo ""
    @echo "Run in separate terminals:"
    @echo "  just dev-backend   # Terminal 1"
    @echo "  just dev-frontend  # Terminal 2"

# Stop dev frontend
dev-down:
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml down

# =============================================================================
# Cloudflare R2 Sync (using rclone)
# Two buckets: dreamgen-gallery (full collection) + continuous-image-gen (latest only)
# =============================================================================

# Sync to BOTH buckets (gallery gets all, latest gets only most recent)
sync:
    @echo "→ Syncing full collection to dreamgen-gallery..."
    @rclone sync output/ r2:dreamgen-gallery --progress --transfers 8 --fast-list
    @echo "→ Syncing latest image to continuous-image-gen..."
    @just sync-latest
    @echo "✓ Both buckets synced!"

# Sync only to gallery bucket (full collection)
sync-gallery:
    rclone sync output/ r2:dreamgen-gallery --progress --transfers 8 --fast-list

# Sync only latest image to continuous-image-gen bucket
sync-latest:
    #!/usr/bin/env bash
    export CLOUDFLARE_ACCOUNT_ID=f5abe6cf148f6acb358556290377dc12
    latest=$(find output -name "*.png" -type f -printf '%T@ %p\n' | sort -rn | head -1 | cut -d' ' -f2)
    if [ -n "$latest" ]; then
        filename=$(basename "$latest")
        echo "Uploading latest: $filename"
        # Try rclone first, fall back to wrangler if token doesn't have access
        if ! rclone copyto "$latest" "r2-latest:continuous-image-gen/$filename" --progress 2>/dev/null; then
            echo "  rclone failed, using wrangler..."
            cd host-image && npx wrangler r2 object put "continuous-image-gen/$filename" --file "../$latest" 2>&1 | grep -v "^$"
        fi
    else
        echo "No images found"
    fi

# Dry run - see what would be synced to both buckets
sync-dry:
    @echo "→ Gallery bucket (all images):"
    @rclone sync output/ r2:dreamgen-gallery --dry-run
    @echo ""
    @echo "→ Latest bucket (most recent only):"
    @just sync-latest

# List gallery bucket contents
r2-list:
    @echo "=== Gallery Bucket (dreamgen-gallery) ==="
    @rclone ls r2:dreamgen-gallery
    @echo ""
    @echo "=== Latest Bucket (continuous-image-gen) ==="
    @rclone ls r2-latest:continuous-image-gen

# List with details (size, modified time)
r2-ls:
    @echo "=== Gallery Bucket ==="
    @rclone lsl r2:dreamgen-gallery
    @echo ""
    @echo "=== Latest Bucket ==="
    @rclone lsl r2-latest:continuous-image-gen

# Check differences between local and R2 gallery
r2-check:
    rclone check output/ r2:dreamgen-gallery

# Delete all R2 objects from BOTH buckets (use with caution!)
r2-clean:
    #!/usr/bin/env bash
    echo "⚠️  This will delete ALL images from BOTH R2 buckets!"
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        echo "Cleaning dreamgen-gallery..."
        rclone delete r2:dreamgen-gallery --verbose
        echo "Cleaning continuous-image-gen..."
        rclone delete r2-latest:continuous-image-gen --verbose
        echo "✓ Both R2 buckets cleaned"
    else
        echo "Cancelled"
    fi

# =============================================================================
# Cloudflare Workers
# =============================================================================

# Deploy image host worker
deploy-host:
    cd host-image && npx wrangler deploy

# Deploy gallery
deploy-gallery:
    cd cloudflare-gallery && npx wrangler pages deploy public

# Deploy everything (host + gallery + sync recent images)
deploy: deploy-host deploy-gallery sync

# =============================================================================
# Web UI
# =============================================================================

# Install web UI dependencies
web-install:
    cd web-ui && npm install

# Start web UI dev server
web:
    cd web-ui && npm run dev

# Build web UI
web-build:
    cd web-ui && npm run build

# =============================================================================
# Monitoring
# =============================================================================

# Show last 10 generated images
recent:
    @ls -t output/*/week_*/*.png 2>/dev/null | head -10 || echo "No images found"

# Count total images
count:
    @find output -name "*.png" | wc -l

# Watch GPU status
gpu:
    watch -n 2 nvidia-smi

# =============================================================================
# Cleanup
# =============================================================================

# Clean Python cache
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete

# Clean Docker
clean-docker:
    docker-compose down -v
    docker system prune -f

# =============================================================================
# Setup
# =============================================================================

# Create .env from example
setup-env:
    cp .env.example .env
    @echo "✓ Created .env - edit with your settings"

# Setup rclone for R2 sync
setup-rclone:
    ./setup-rclone-r2.sh

# Full setup
setup: setup-env install web-install
    @echo "✓ Setup complete! Edit .env and run 'just gen' or 'just up'"
    @echo "  To enable R2 sync, run: just setup-rclone"
