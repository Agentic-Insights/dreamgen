---
name: docker-hot-reload
description: Run local application stacks in Docker with bind-mounted source hot reload. Use when changing DreamGen or similar repo runtime workflows, Docker Compose overlays, local deploy/test commands, port wiring, Next.js/FastAPI dev containers, or when debugging stale localhost containers versus current worktree code.
---

# Docker Hot Reload

## Overview

Keep Docker as the primary local runtime while preserving fast edit-refresh
loops through bind-mounted source directories. Avoid adding host-run dev servers
as a backup path unless the user explicitly asks for one.

## Pattern

- Start from the production Compose file, then add a hot-reload override file.
- Keep dependencies and OS packages inside images.
- Bind-mount only actively edited source, config, scripts, and data folders.
- Keep dependency directories container-owned, such as `/app/node_modules`, so a
  host mount does not erase installed packages.
- Preserve named volumes or stable mounts for caches, generated output, model
  checkpoints, LoRAs, and logs.
- Use the same public ports as review and parity runs so Browser checks do not
  drift.

## Backend Containers

- Override both `entrypoint` and `command` when the base image entrypoint already
  launches the app. Do not put a second executable into `command` behind an
  inherited entrypoint.
- Run the framework-native reloader inside Docker, for example:

```yaml
entrypoint: ["/opt/venv/bin/python", "-m", "uvicorn"]
command:
  - src.api.server:app
  - --host
  - 0.0.0.0
  - --port
  - "8000"
  - --reload
  - --reload-dir
  - /app/src
```

## Frontend Containers

- Use a dev Dockerfile when production images do not include dev dependencies.
- Mount the frontend source tree and protect `node_modules` with an anonymous or
  named volume:

```yaml
volumes:
  - ./web-ui:/app
  - /app/node_modules
```

- For browser-executed code, set public API URLs to the host-published port, not
  the internal Compose service URL. Example: `http://localhost:25800`.

## DreamGen Commands

Use these commands in this repository:

```powershell
just dev-docker-hot
just verify-live
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.hot.yml logs -f backend frontend
just deploy-local-docker
```

`just dev-docker-hot` is the normal perpetually running development path.
`just deploy-local-docker` is for rebuilt production-style image parity.

## Verification

Before handoff, verify the live app, not just the source tree:

- Run Compose config validation for the hot overlay.
- Check `docker compose ... ps` and logs for backend/frontend health.
- Run `just verify-live`; it checks both `127.0.0.1` and `localhost` so stale
  Docker/WSL listeners do not hide behind a healthy process.
- Use the in-app Browser to reload the UI and check for Next.js error overlays.

## Common Failures

- `Failed to fetch` in the UI usually means the browser-facing API URL points at
  the wrong host/port or a stale listener owns the API port.
- A container that exits immediately after adding a reload command often still
  has the base image entrypoint; override `entrypoint`.
- Missing frontend packages after mounting the source tree usually means
  `/app/node_modules` was overwritten by the bind mount.
- A healthy `localhost:7860` page is not proof of current code; verify route
  shape through OpenAPI and refresh the Browser.
