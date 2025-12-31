# Contributing to DreamGen

Thank you for your interest in contributing to DreamGen! This guide will help you set up your development environment and understand our code quality standards.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- uv package manager
- Docker (optional, for containerized development)
- NVIDIA GPU with CUDA 12.4+ (optional, CPU mode available)

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/killerapp/dreamgen
cd dreamgen

# Run sanity checks to verify your environment
just sanity

# Install dependencies
just install
cd web-ui && npm install

# Set up environment
cp .env.example .env
# Edit .env with your configuration

# Install pre-commit hooks
just hooks-install
```

## Code Quality Standards

We maintain high code quality through automated checks and linting.

### Python Code Style

- **Formatter**: Black (line length: 100)
- **Import sorting**: isort (black-compatible)
- **Linter**: Pylint
- **Type checker**: mypy

### JavaScript/TypeScript Code Style

- **Linter**: ESLint with Next.js configuration
- **Framework**: Next.js 15 + React 19

## Running Checks

### Quick Checks (Fast)

```bash
# Format Python code
just fmt

# Lint Python (errors only)
just lint-errors

# Run tests
just test

# Quick check (format + lint + test)
just check
```

### Comprehensive Checks (CI-style)

```bash
# All Python checks
just check-all

# Environment sanity checks
just sanity

# Web UI linting
just web-lint

# Run pre-commit hooks
just hooks-run
```

### Individual Check Commands

```bash
# Python formatting
just fmt

# Python linting (full)
just lint

# Python type checking
just typecheck

# Python tests with coverage
just test-cov

# Web UI linting
just web-lint

# Fix web UI linting issues
just web-lint-fix
```

## Pre-commit Hooks

We use pre-commit hooks to ensure code quality before commits:

```bash
# Install hooks (one-time)
just hooks-install

# Run hooks manually
just hooks-run

# Update hook versions
just hooks-update
```

Hooks automatically run on `git commit` and check:
- Python formatting (black, isort)
- Python linting (pylint - errors only)
- File formatting (trailing whitespace, end-of-file)
- YAML/JSON/TOML syntax
- Shell script linting (shellcheck)
- Merge conflict markers
- Large files
- Private keys

## Testing

### Running Tests

```bash
# All tests
just test

# With coverage report
just test-cov

# Specific test file
uv run pytest tests/test_mock_generator.py

# With verbose output
uv run pytest tests/ -v
```

### Writing Tests

- Place tests in `tests/` directory
- Name test files `test_*.py`
- Use `pytest` fixtures and async support
- Aim for >80% code coverage

Example test:

```python
import pytest
from src.generators.mock_image_generator import MockImageGenerator

@pytest.mark.asyncio
async def test_generate_image():
    generator = MockImageGenerator()
    result = await generator.generate("test prompt")
    assert result is not None
```

## Sanity Checks

The `sanity-check.sh` script validates your environment:

```bash
just sanity
```

It checks:
1. **Environment**: Python, uv, Node.js, Docker, CUDA/GPU
2. **Configuration**: .env file, required settings
3. **Dependencies**: Virtual env, Python packages, Node modules
4. **File Structure**: Critical directories and files
5. **Code Quality**: Syntax, imports, TODOs
6. **Services**: Ollama, Docker daemon
7. **Git**: Repository status, pre-commit hooks

## Continuous Integration

Our CI pipeline runs:

```bash
just check-all  # Format, lint, typecheck, test, web-lint
```

Make sure this passes before opening a PR.

## Common Issues

### Import errors in tests

If you see import errors when running tests:
```bash
uv sync  # Reinstall dependencies
```

### Pre-commit hook failures

```bash
# Fix formatting issues
just fmt

# Run hooks to see what failed
just hooks-run

# Skip hooks in emergency (not recommended)
git commit --no-verify
```

### Linting errors

```bash
# See full lint report
just lint

# Fix auto-fixable issues
just fmt

# Type check issues
just typecheck
```

## Project Structure

```
dreamgen/
├── src/              # Python source code
│   ├── generators/   # Image and prompt generators
│   ├── plugins/      # Plugin system
│   ├── utils/        # Utilities and helpers
│   └── main.py       # CLI entry point
├── tests/            # Python tests
├── web-ui/           # Next.js web interface
│   ├── app/          # Next.js app router
│   ├── components/   # React components
│   └── lib/          # Utilities
├── host-image/       # Cloudflare Worker (latest image)
├── cloudflare-gallery/ # Cloudflare Pages (gallery)
├── data/             # JSON data files
├── output/           # Generated images
└── logs/             # Application logs
```

## Making Changes

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes
3. Run checks: `just check-all`
4. Run sanity checks: `just sanity`
5. Commit with conventional commits: `git commit -m "feat: add new feature"`
6. Push and open a PR

### Commit Message Format

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting)
- `refactor:` Code refactoring
- `test:` Test changes
- `chore:` Build/tooling changes

## Getting Help

- **Issues**: https://github.com/killerapp/dreamgen/issues
- **Discussions**: https://github.com/killerapp/dreamgen/discussions
- **Documentation**: See README.md and CLAUDE.md

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
