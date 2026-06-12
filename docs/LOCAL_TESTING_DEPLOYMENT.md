# Local Testing And Deployment

DreamGen is expected to run like a local dream machine: often-on, local-first,
and quick to inspect. The default local runtime is Docker with bind-mounted
source and hot reload, so the running app matches container wiring while still
reflecting code edits quickly.

## Lanes

### 1. Docker Hot Reload

Use this as the normal perpetual development runtime. It keeps backend and
frontend in Docker while mounting source folders for hot reload.

```powershell
just dev-docker-hot
```

This runs Compose with `docker-compose.hot.yml`, mounting:

- `./src:/app/src`
- `./data:/app/data`
- `./scripts:/app/scripts`
- `./web-ui:/app`
- model/cache/output/log/LoRA/checkpoint folders from the base Compose file

The backend runs `uvicorn --reload` inside Docker. The frontend runs Next.js dev
inside Docker with the source tree mounted.

### 2. Full Docker Parity

Use before handing off Docker-specific work or when validating production-style
images.

```powershell
just deploy-local-docker
```

This rebuilds and starts the regular Docker Compose stack without relying on
source mounts.

## Always Verify What Is Live

The app may already be running on `localhost:7860`, but it may be an old Docker
image. Verify the current serving surface before handoff:

```powershell
just verify-live
```

The verification checks:

- API health at `http://127.0.0.1:25800/api/status`
- UI health at `http://127.0.0.1:7860`
- matching route shape at both `http://127.0.0.1:25800` and
  `http://localhost:25800`, so stale Docker/WSL listeners do not hide behind a
  healthy host backend
- expected current routes, such as `/api/compare`
- forbidden stale routes, such as `/api/batch` and `/api/edit`

For route-specific work, update `scripts/verify-live.ps1` arguments or run a
targeted OpenAPI check:

```powershell
$openapi = Invoke-RestMethod http://127.0.0.1:25800/openapi.json
$openapi.paths.PSObject.Properties.Name | Where-Object { $_ -match '/api/(compare|batch|edit)' }
```

## Publication Tools

Local deployment only makes the app visible on this machine. Publication is a
separate, deliberate step.

Preview approved gallery publication:

```powershell
just publish-dry
```

Publish approved, non-placeholder gallery assets:

```powershell
just publish-approved
```

Deploy Cloudflare workers/pages:

```powershell
just deploy-host
just deploy-gallery
```

Use `just deploy` only when you intend to deploy workers/pages and sync images.
