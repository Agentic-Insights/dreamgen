# Mage-Flow-Edit verification record

Rechecked on 2026-08-16 from `codex/mage-edit-studio`, based on current
`origin/main` after PR #72 merged.

## Automated checks

- `uv run --frozen pytest tests/ -q`: **161 passed, 1 skipped**; two existing
  FastAPI `on_event` deprecation warnings.
- `uv run --frozen black --check src tests mageflow-service`: clean.
- `uv run --frozen isort --check-only src tests mageflow-service`: clean.
- `npm run build` in `web-ui`: production compile, lint, and type check passed.
- Fresh Docker images built for sidecar, backend, and frontend. All three services
  became healthy at `localhost:25801`, `localhost:25800`, and `localhost:7860`.
- The API, CLI, sidecar, Studio, retry path, and immutable job metadata now carry
  one to three ordered references. Deterministic tests cover two-reference
  transport/lineage and rejection of a fourth reference.

## Live local runtime

- GPU: NVIDIA GeForce RTX 4090.
- Sidecar-reported VRAM during the Docker check: 23,030 MiB total, 21,463 MiB free.
- `/api/edit/capabilities`: official name `Mage-Flow-Edit`; exact Base, aligned,
  and Turbo Microsoft repositories; `available=false`; no verified checkpoint
  revisions configured; no fallback.
- `official-access-reaudit-2026-08-16.json`: anonymous API/resolve requests and an
  authenticated browser recheck confirm 401/404 for the exact repositories, no
  standard gate, and no edit checkpoint in Microsoft's current live Mage collection.
  Search-indexed transient publication records are recorded but not accepted as
  downloadable checkpoint provenance. No credential is recorded.
- Microsoft's implementation is pinned to
  `76bec2bb3818863f470de7e867c2dc7f1d0bfd83`; the three commits since the previous
  pin only change documentation/citation assets, not runtime code.
- The current screenshots show the truthful unavailable boundary and ordered
  primary/reference staging on fresh Docker desktop and 390 px mobile surfaces.
- `studio-edit-desktop-multiref.png` labels the comparison as **original preview ·
  no edit output**. The two mobile diagnostic captures watermark the fixture as
  **not model output** and show the disabled decision/retry/branch/publish controls.
- The staged screenshots use the legacy mock editor only to exercise responsive
  compare/history/action layout. Both views label it **diagnostic fixture**, state
  that it is not Mage-Flow-Edit output, and disable approve/retry/branch/publish.

## Independent validation

An independent validator reviewed the desktop/mobile screenshots, Studio IA,
supported controls, runtime/VRAM state, queue semantics, provenance, API, and
Cloudflare gates. The latest review caught that diagnostic fixtures were protected
in the UI and publication gate but could still receive an API decision. The server
now returns HTTP 409 for any diagnostic decision; a deterministic test and a live
Docker probe cover the gate. Persistent original/diagnostic overlays and lower-page
mobile evidence were also added. Final result: **PASS for draft PR readiness**.

The validator explicitly confirms this is **not release-ready for real inference**:
the official checkpoints remain inaccessible, so there is no genuine edit output or
RTX 4090 Turbo/aligned latency and peak-memory benchmark.

## Cloudflare endpoint

Read-only checks on 2026-08-16 returned HTTP 200 from
`https://dreamgen.agenticinsights.com/` and `/api/images`. The API response carried
release `20260731-96377d84c54dbd25`; all 336 records had a release ID and a
content-versioned image URL. See `cloudflare-endpoint.json` and
`cloudflare-headers.txt`. No asset or release pointer was modified.
