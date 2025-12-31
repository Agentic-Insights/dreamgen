# Code Quality & Testing Guide

This document describes the linting, testing, and code quality practices for DreamGen.

## Quick Reference

```bash
# Quick checks before commit
just check          # Format + lint (errors) + test

# Comprehensive checks (CI-style)
just check-all      # Format + full lint + typecheck + test + web-lint

# Environment validation
just sanity         # Check environment, config, dependencies

# Pre-commit hooks
just hooks-install  # Install hooks (one-time)
just hooks-run      # Run all hooks manually
```

## Overview

DreamGen maintains high code quality through:

1. **Automated formatting** (Black, isort)
2. **Static analysis** (Pylint, mypy, ESLint)
3. **Pre-commit hooks** (runs on `git commit`)
4. **Continuous integration** (GitHub Actions)
5. **Environment sanity checks** (validates setup)

## Tools & Configuration

### Python

| Tool | Purpose | Config | Command |
|------|---------|--------|---------|
| **Black** | Code formatting | `pyproject.toml` | `just fmt` |
| **isort** | Import sorting | `pyproject.toml` | `just fmt` |
| **Pylint** | Linting | `.pylintrc` | `just lint` |
| **mypy** | Type checking | `mypy.ini` | `just typecheck` |
| **pytest** | Testing | `pyproject.toml` | `just test` |

### JavaScript/TypeScript

| Tool | Purpose | Config | Command |
|------|---------|--------|---------|
| **ESLint** | Linting | `eslint.config.mjs` | `just web-lint` |
| **Next.js** | Build/type check | `next.config.ts` | `cd web-ui && npm run build` |

### Shell Scripts

| Tool | Purpose | Config | Command |
|------|---------|--------|---------|
| **shellcheck** | Shell linting | `.pre-commit-config.yaml` | `just hooks-run` |

## Pre-commit Hooks

Pre-commit hooks run automatically on `git commit` and prevent commits with issues.

### Installation

```bash
just hooks-install
```

### What Gets Checked

- ✓ Python formatting (black, isort)
- ✓ Python linting (pylint - errors only)
- ✓ Trailing whitespace
- ✓ End-of-file fixing
- ✓ YAML/JSON/TOML syntax
- ✓ Shell script linting
- ✓ Merge conflict markers
- ✓ Large files (>1MB)
- ✓ Private keys detection

### Running Manually

```bash
# Run on all files
just hooks-run

# Run on staged files only
git commit  # Hooks run automatically

# Skip hooks (not recommended)
git commit --no-verify
```

### Updating Hooks

```bash
just hooks-update
```

## Sanity Checks

The sanity check script validates your development environment.

### Running

```bash
just sanity
```

### What Gets Checked

1. **Environment Checks** (7 checks)
   - Python version (3.11+)
   - uv package manager
   - Node.js
   - Docker
   - Git
   - CUDA/GPU (optional)

2. **Configuration Checks** (5 checks)
   - .env file exists
   - Required environment variables set
   - pyproject.toml exists
   - Output directory

3. **Dependency Checks** (4 checks)
   - Virtual environment
   - PyTorch installed
   - Diffusers installed
   - Web UI node_modules

4. **File Structure Checks** (9 checks)
   - Critical directories exist
   - Critical files exist
   - Data files present

5. **Code Quality Checks** (4 checks)
   - Python syntax valid
   - No wildcard imports
   - Print statements (warning)
   - TODO/FIXME comments (warning)

6. **Service Checks** (2 checks)
   - Ollama service
   - Docker daemon

7. **Git Repository Checks** (4 checks)
   - Repository initialized
   - Current branch
   - Uncommitted changes (warning)
   - Pre-commit hooks installed

### Output

```
=== DreamGen Sanity Checks ===

[1/7] Environment Checks
✓ Python version: 3.12.3
✓ uv package manager: 0.9.5
✓ GPU: NVIDIA GeForce RTX 4090 (CUDA 12.8)

[2/7] Configuration Checks
✓ .env file exists
✓ OLLAMA_MODEL configured

...

=== Summary ===
Passed:   30
Warnings: 4
Failed:   0

✓ All critical checks passed!
⚠ 4 warnings - consider addressing them
```

## Testing

### Running Tests

```bash
# All tests
just test

# With coverage report (HTML + terminal)
just test-cov

# Specific test file
uv run pytest tests/test_mock_generator.py

# Verbose output
uv run pytest tests/ -v

# Stop on first failure
uv run pytest tests/ -x
```

### Coverage

Coverage reports are generated in:
- Terminal: Shown after `just test-cov`
- HTML: `htmlcov/index.html`

Target: **>80% coverage**

### Writing Tests

Place tests in `tests/` directory:

```python
import pytest
from src.generators.mock_image_generator import MockImageGenerator

@pytest.mark.asyncio
async def test_generate_image():
    """Test mock image generation"""
    generator = MockImageGenerator()
    result = await generator.generate("test prompt")

    assert result is not None
    assert result.image_path.exists()
    assert result.prompt == "test prompt"
```

## Linting

### Python Linting

```bash
# Quick lint (errors only, fast)
just lint-errors

# Full lint (with warnings)
just lint

# Specific file
uv run pylint src/main.py
```

### Web UI Linting

```bash
# Lint
just web-lint

# Lint and fix
just web-lint-fix
```

### Configuration

**Pylint** (`.pylintrc`):
- Max line length: 100
- Disabled: docstring requirements, some naming conventions
- Errors-only mode for pre-commit (fast)

**ESLint** (`eslint.config.mjs`):
- Next.js recommended config
- TypeScript support
- Core Web Vitals rules

## Type Checking

```bash
# Type check Python code
just typecheck

# Specific file
uv run mypy src/main.py
```

### Configuration

**mypy** (`mypy.ini`):
- Python 3.11+
- Ignore missing imports (ML libraries)
- No strict optional
- Excludes: venv, node_modules, output, tests

## Continuous Integration

GitHub Actions runs on every push and PR:

### Jobs

1. **sanity-check** - Environment validation
2. **python-checks** - Format, lint, type check
3. **python-tests** - Tests with coverage
4. **web-ui-checks** - Lint and build
5. **pre-commit** - All pre-commit hooks

### Workflow File

`.github/workflows/ci.yml`

### Status Badges

Add to README.md:

```markdown
![CI](https://github.com/killerapp/dreamgen/workflows/CI/badge.svg)
```

## Common Issues

### Black and isort conflict

Already configured to work together via `profile = "black"` in isort config.

### Import errors in tests

```bash
uv sync  # Reinstall dependencies
```

### Pylint import errors

Use `--disable=import-error` or add to `.pylintrc`:

```ini
[MESSAGES CONTROL]
disable=import-error
```

### Pre-commit hook too slow

Use errors-only mode (already configured):

```yaml
args: [--errors-only]
```

### Skip checks temporarily

```bash
# Skip pre-commit hooks
git commit --no-verify

# Skip specific pytest
pytest -k "not test_slow"
```

## Best Practices

1. **Before committing**:
   ```bash
   just check        # Quick checks
   just sanity       # Environment checks
   ```

2. **Before PR**:
   ```bash
   just check-all    # All checks
   just test-cov     # Coverage report
   ```

3. **Format on save**: Configure your IDE to run black/isort on save

4. **Fix issues early**: Don't accumulate linting issues

5. **Write tests**: Aim for >80% coverage

6. **Use type hints**: Help mypy catch bugs early

7. **Check CI**: Ensure GitHub Actions passes before merging

## IDE Integration

### VS Code

`.vscode/settings.json`:

```json
{
  "python.formatting.provider": "black",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true
  }
}
```

### PyCharm

1. Settings → Tools → Black → Enable
2. Settings → Tools → External Tools → Add isort
3. Settings → Editor → Inspections → Enable Pylint

## Maintenance

### Update dependencies

```bash
# Python
uv sync --upgrade

# Web UI
cd web-ui && npm update

# Pre-commit hooks
just hooks-update
```

### Update linting rules

Edit configuration files:
- `.pylintrc` - Pylint rules
- `mypy.ini` - mypy settings
- `web-ui/eslint.config.mjs` - ESLint rules
- `.pre-commit-config.yaml` - Hook versions

## Resources

- [Black](https://black.readthedocs.io/)
- [isort](https://pycqa.github.io/isort/)
- [Pylint](https://pylint.pycqa.org/)
- [mypy](https://mypy.readthedocs.io/)
- [pytest](https://pytest.org/)
- [pre-commit](https://pre-commit.com/)
- [ESLint](https://eslint.org/)
- [shellcheck](https://www.shellcheck.net/)
