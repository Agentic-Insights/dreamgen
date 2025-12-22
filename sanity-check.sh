#!/bin/bash
# DreamGen Sanity Checks
# Verifies environment, dependencies, configuration, and code quality

# Note: Not using set -e to continue checks even if some fail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

echo -e "${BLUE}=== DreamGen Sanity Checks ===${NC}\n"

# Helper functions
check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAILED++))
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

# =============================================================================
# 1. Environment Checks
# =============================================================================
echo -e "${BLUE}[1/7] Environment Checks${NC}"

# Check Python version
if command -v python3 >/dev/null 2>&1; then
    PY_VERSION=$(python3 --version | cut -d' ' -f2)
    if [[ "$PY_VERSION" == 3.11.* ]] || [[ "$PY_VERSION" == 3.12.* ]]; then
        check_pass "Python version: $PY_VERSION"
    else
        check_warn "Python version $PY_VERSION (expected 3.11+)"
    fi
else
    check_fail "Python 3 not found"
fi

# Check uv
if command -v uv >/dev/null 2>&1; then
    UV_VERSION=$(uv --version | cut -d' ' -f2)
    check_pass "uv package manager: $UV_VERSION"
else
    check_fail "uv not found (install: curl -LsSf https://astral.sh/uv/install.sh | sh)"
fi

# Check Node.js
if command -v node >/dev/null 2>&1; then
    NODE_VERSION=$(node --version)
    check_pass "Node.js: $NODE_VERSION"
else
    check_warn "Node.js not found (needed for web-ui)"
fi

# Check Docker
if command -v docker >/dev/null 2>&1; then
    DOCKER_VERSION=$(docker --version | cut -d' ' -f3 | tr -d ',')
    check_pass "Docker: $DOCKER_VERSION"
else
    check_warn "Docker not found (needed for containerized deployment)"
fi

# Check Git
if command -v git >/dev/null 2>&1; then
    GIT_VERSION=$(git --version | cut -d' ' -f3)
    check_pass "Git: $GIT_VERSION"
else
    check_warn "Git not found"
fi

# Check CUDA/GPU
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
    CUDA_VERSION=$(nvidia-smi | grep "CUDA Version" | awk '{print $9}')
    check_pass "GPU: $GPU_NAME (CUDA $CUDA_VERSION)"
else
    check_warn "NVIDIA GPU not detected (CPU-only mode available)"
fi

echo ""

# =============================================================================
# 2. Configuration Checks
# =============================================================================
echo -e "${BLUE}[2/7] Configuration Checks${NC}"

# Check .env file
if [ -f .env ]; then
    check_pass ".env file exists"

    # Check required env vars
    if grep -q "OLLAMA_MODEL" .env && [ -n "$(grep OLLAMA_MODEL .env | cut -d'=' -f2)" ]; then
        check_pass "OLLAMA_MODEL configured"
    else
        check_fail "OLLAMA_MODEL not set in .env"
    fi

    if grep -q "FLUX_MODEL" .env && [ -n "$(grep FLUX_MODEL .env | cut -d'=' -f2)" ]; then
        check_pass "FLUX_MODEL configured"
    else
        check_fail "FLUX_MODEL not set in .env"
    fi
else
    check_fail ".env file missing (run: cp .env.example .env)"
fi

# Check pyproject.toml
if [ -f pyproject.toml ]; then
    check_pass "pyproject.toml exists"
else
    check_fail "pyproject.toml missing"
fi

# Check output directory
if [ -d output ]; then
    IMAGE_COUNT=$(find output -name "*.png" 2>/dev/null | wc -l)
    check_pass "Output directory exists ($IMAGE_COUNT images)"
else
    check_warn "Output directory doesn't exist (will be created)"
fi

echo ""

# =============================================================================
# 3. Dependency Checks
# =============================================================================
echo -e "${BLUE}[3/7] Dependency Checks${NC}"

# Check if virtual environment exists
if [ -d .venv ]; then
    check_pass "Virtual environment exists"

    # Check if dependencies are installed
    if ls .venv/lib/python*/site-packages/torch/__init__.py >/dev/null 2>&1; then
        check_pass "PyTorch installed"
    else
        check_warn "PyTorch not found (run: uv sync)"
    fi

    if ls .venv/lib/python*/site-packages/diffusers/__init__.py >/dev/null 2>&1; then
        check_pass "Diffusers installed"
    else
        check_warn "Diffusers not found (run: uv sync)"
    fi
else
    check_fail "Virtual environment missing (run: uv sync)"
fi

# Check web-ui dependencies
if [ -d web-ui/node_modules ]; then
    check_pass "Web UI dependencies installed"
else
    check_warn "Web UI dependencies missing (run: cd web-ui && npm install)"
fi

echo ""

# =============================================================================
# 4. File Structure Checks
# =============================================================================
echo -e "${BLUE}[4/7] File Structure Checks${NC}"

# Check critical directories
for dir in src src/generators src/plugins src/utils tests; do
    if [ -d "$dir" ]; then
        check_pass "Directory exists: $dir"
    else
        check_fail "Missing directory: $dir"
    fi
done

# Check critical files
for file in src/main.py src/__init__.py README.md; do
    if [ -f "$file" ]; then
        check_pass "File exists: $file"
    else
        check_fail "Missing file: $file"
    fi
done

# Check data files
if [ -f data/art_styles.json ]; then
    STYLES_COUNT=$(jq '. | length' data/art_styles.json 2>/dev/null || echo "0")
    check_pass "Art styles data: $STYLES_COUNT styles"
else
    check_fail "Missing data/art_styles.json"
fi

echo ""

# =============================================================================
# 5. Code Quality Checks
# =============================================================================
echo -e "${BLUE}[5/7] Code Quality Checks${NC}"

# Check Python syntax
echo -n "Checking Python syntax... "
if python3 -m py_compile src/**/*.py 2>/dev/null; then
    check_pass "Python syntax valid"
else
    check_fail "Python syntax errors found"
fi

# Check for common issues
if grep -r "import \*" src/ 2>/dev/null | grep -v ".pyc" | grep -q .; then
    check_warn "Found wildcard imports (consider being explicit)"
else
    check_pass "No wildcard imports"
fi

# Check for print statements (should use logging)
PRINT_COUNT=$(grep -r "print(" src/ 2>/dev/null | grep -v ".pyc" | wc -l)
if [ "$PRINT_COUNT" -gt 0 ]; then
    check_warn "Found $PRINT_COUNT print() statements (consider using logging)"
else
    check_pass "No print() statements"
fi

# Check for TODO/FIXME comments
TODO_COUNT=$(grep -r "TODO\|FIXME" src/ 2>/dev/null | wc -l)
if [ "$TODO_COUNT" -gt 0 ]; then
    check_warn "Found $TODO_COUNT TODO/FIXME comments"
else
    check_pass "No TODO/FIXME comments"
fi

echo ""

# =============================================================================
# 6. Service Checks
# =============================================================================
echo -e "${BLUE}[6/7] Service Checks${NC}"

# Check Ollama
if command -v ollama >/dev/null 2>&1; then
    check_pass "Ollama CLI installed"

    # Try local Ollama
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        check_pass "Ollama service running (localhost)"
    # Try WSL gateway
    elif curl -s http://172.30.224.1:11434/api/tags >/dev/null 2>&1; then
        check_pass "Ollama service running (WSL gateway)"
    else
        check_warn "Ollama service not responding"
    fi
else
    check_warn "Ollama CLI not found"
fi

# Check if Docker is running
if command -v docker >/dev/null 2>&1; then
    if docker ps >/dev/null 2>&1; then
        check_pass "Docker daemon running"
    else
        check_warn "Docker daemon not running"
    fi
fi

echo ""

# =============================================================================
# 7. Git Repository Checks
# =============================================================================
echo -e "${BLUE}[7/7] Git Repository Checks${NC}"

if [ -d .git ]; then
    check_pass "Git repository initialized"

    # Check branch
    BRANCH=$(git branch --show-current 2>/dev/null)
    if [ -n "$BRANCH" ]; then
        check_pass "Current branch: $BRANCH"
    fi

    # Check for uncommitted changes
    if [ -z "$(git status --porcelain)" ]; then
        check_pass "Working directory clean"
    else
        CHANGED=$(git status --porcelain | wc -l)
        check_warn "$CHANGED uncommitted changes"
    fi

    # Check for pre-commit hooks
    if [ -f .git/hooks/pre-commit ]; then
        check_pass "Pre-commit hooks installed"
    else
        check_warn "Pre-commit hooks not installed (run: uv run pre-commit install)"
    fi
else
    check_warn "Not a git repository"
fi

echo ""

# =============================================================================
# Summary
# =============================================================================
echo -e "${BLUE}=== Summary ===${NC}"
echo -e "${GREEN}Passed:${NC}   $PASSED"
echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
echo -e "${RED}Failed:${NC}   $FAILED"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}✓ All critical checks passed!${NC}"
    if [ "$WARNINGS" -gt 0 ]; then
        echo -e "${YELLOW}⚠ $WARNINGS warnings - consider addressing them${NC}"
    fi
    exit 0
else
    echo -e "${RED}✗ $FAILED critical checks failed${NC}"
    echo "Please fix the issues above before proceeding."
    exit 1
fi
