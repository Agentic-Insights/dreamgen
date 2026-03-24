# Code Quality Setup Summary

This document summarizes all the scanning, linting, and sanity check infrastructure added to DreamGen.

## What Was Added

### 1. Configuration Files

| File | Purpose |
|------|---------|
| `.pre-commit-config.yaml` | Pre-commit hook configuration |
| `.pylintrc` | Python linting rules |
| `mypy.ini` | Python type checking configuration |
| `sanity-check.sh` | Comprehensive environment validation script |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline |

### 2. Documentation

| File | Purpose |
|------|---------|
| `CODE_QUALITY.md` | Complete guide to code quality tools and practices |
| `CONTRIBUTING.md` | Contribution guidelines with quality standards |
| `QUALITY_SETUP_SUMMARY.md` | This file - setup overview |

### 3. Justfile Commands

New commands added to `justfile`:

```bash
# Code quality
just check           # Quick checks (format + lint-errors + test)
just check-all       # Comprehensive checks (CI-style)
just sanity          # Environment sanity checks

# Formatting
just fmt             # Format Python code (black + isort)

# Linting
just lint            # Full Python linting
just lint-errors     # Python errors only (fast)
just web-lint        # Web UI linting
just web-lint-fix    # Fix web UI issues

# Type checking
just typecheck       # Python type checking

# Testing
just test            # Run tests
just test-cov        # Tests with coverage

# Pre-commit hooks
just hooks-install   # Install hooks (one-time)
just hooks-run       # Run hooks manually
just hooks-update    # Update hook versions
```

## Quick Start

### Initial Setup

```bash
# Install pre-commit hooks
just hooks-install

# Verify environment
just sanity

# Run all checks
just check
```

### Before Committing

```bash
# Format and check code
just check

# Or let pre-commit hooks do it automatically
git commit -m "your message"
```

### Before Opening PR

```bash
# Run comprehensive checks
just check-all

# Verify environment
just sanity
```

## What Gets Checked

### Pre-commit Hooks (Automatic on `git commit`)

✓ Python formatting (black, isort)
✓ Python linting (pylint - errors only)
✓ File formatting (whitespace, end-of-file)
✓ YAML/JSON/TOML syntax
✓ Shell script linting (shellcheck)
✓ Large files detection
✓ Private key detection
✓ Merge conflict markers

### Sanity Checks (`just sanity`)

1. **Environment**: Python, uv, Node.js, Docker, Git, CUDA/GPU
2. **Configuration**: .env file, required settings
3. **Dependencies**: Virtual env, packages, node_modules
4. **File Structure**: Critical directories and files
5. **Code Quality**: Syntax, imports, TODOs
6. **Services**: Ollama, Docker daemon
7. **Git**: Repository status, hooks installed

### CI Pipeline (GitHub Actions)

- **sanity-check**: Environment validation
- **python-checks**: Format check, lint, type check
- **python-tests**: Tests with coverage
- **web-ui-checks**: Lint and build
- **pre-commit**: All hooks

## Code Quality Standards

### Python

- **Formatter**: Black (line length: 100)
- **Import sorting**: isort (black-compatible)
- **Linter**: Pylint
- **Type checker**: mypy
- **Test framework**: pytest
- **Coverage target**: >80%

### TypeScript/JavaScript

- **Linter**: ESLint with Next.js config
- **Framework**: Next.js 15 + React 19
- **Type checking**: TypeScript

### Shell Scripts

- **Linter**: shellcheck

## Configuration Details

### Black (`pyproject.toml`)

```toml
[tool.black]
line-length = 100
target-version = ["py311"]
```

### isort (`pyproject.toml`)

```toml
[tool.isort]
profile = "black"
line_length = 100
multi_line_output = 3
```

### Pylint (`.pylintrc`)

- Max line length: 100
- Max args: 10
- Max branches: 15
- Disabled: missing-docstring, invalid-name, too-few-public-methods

### mypy (`mypy.ini`)

- Python 3.11+
- Ignore missing imports
- Exclude: .venv, node_modules, output, tests

## Workflow Integration

### Local Development

1. Make changes
2. Run `just check` (or let pre-commit hooks handle it)
3. Commit changes
4. Push

### CI/CD

1. Push to GitHub
2. GitHub Actions runs all checks
3. Review results
4. Merge if passing

## Troubleshooting

### Pre-commit hooks failing

```bash
# See what failed
just hooks-run

# Fix formatting
just fmt

# Check specific issues
just lint-errors
```

### Sanity checks failing

```bash
# Run verbose
./sanity-check.sh

# Fix common issues:
# - Missing .env: cp .env.example .env
# - Missing deps: uv sync
# - Missing web deps: cd web-ui && npm install
# - Hooks not installed: just hooks-install
```

### CI failing

```bash
# Run same checks locally
just check-all

# Check specific job
just test           # For python-tests job
just web-lint       # For web-ui-checks job
just hooks-run      # For pre-commit job
```

## Files Modified

### Enhanced

- `justfile` - Added 15+ new commands for quality checks
- `.pre-commit-config.yaml` - Enhanced with more hooks
- `.github/workflows/ci.yml` - Updated CI pipeline

### Created

- `.pylintrc` - Python linting configuration
- `mypy.ini` - Type checking configuration
- `sanity-check.sh` - Environment validation script
- `CODE_QUALITY.md` - Comprehensive quality guide
- `CONTRIBUTING.md` - Contribution guidelines
- `QUALITY_SETUP_SUMMARY.md` - This file

## Statistics

### Sanity Check Results

```
Passed:   30 checks
Warnings: 4 checks
Failed:   0 checks
```

Warnings:
- 87 print() statements (should use logging)
- Ollama CLI not found (optional)
- 22 uncommitted changes (normal during setup)
- Pre-commit hooks not installed (fixed)

### Pre-commit Hooks

- 7 hook categories
- 15+ individual checks
- Runs in <10 seconds

### CI Pipeline

- 4 jobs
- ~3-5 minute runtime
- Runs on push and PR

## Benefits

1. **Consistent Code Style**: Black + isort ensure uniform formatting
2. **Early Bug Detection**: Pylint + mypy catch issues before runtime
3. **Automated Checks**: Pre-commit hooks prevent bad commits
4. **Environment Validation**: Sanity checks catch config issues early
5. **CI/CD Integration**: GitHub Actions ensures quality on every push
6. **Documentation**: Clear guides for contributors
7. **Fast Feedback**: Error-only mode for quick checks

## Next Steps

1. **Review warnings**: Address the 87 print() statements
2. **Add tests**: Increase coverage to >80%
3. **Configure IDE**: Set up format-on-save
4. **Run regularly**: Make `just check` part of your workflow
5. **Monitor CI**: Check GitHub Actions after each push

## Resources

- `CODE_QUALITY.md` - Detailed quality guide
- `CONTRIBUTING.md` - Contribution guide
- `just --list` - All available commands
- `.pre-commit-config.yaml` - Hook configuration
- `.github/workflows/ci.yml` - CI configuration

## Support

For issues or questions:
- Check `CODE_QUALITY.md` for detailed guides
- Run `just sanity` to validate environment
- Check GitHub Actions logs for CI failures
- Open an issue on GitHub
