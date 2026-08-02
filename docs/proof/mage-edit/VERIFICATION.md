# Mage-Flow-Edit verification record

Checked on 2026-08-02 from `codex/mage-edit-studio`, based on current `origin/main`
after PR #72 merged.

## Automated checks

- `uv run --frozen pytest tests/ -q`: **154 passed, 1 skipped**; two existing
  FastAPI `on_event` deprecation warnings.
- `uv run --frozen black --check src tests mageflow-service`: clean.
- `uv run --frozen isort --check-only src tests mageflow-service`: clean.
- `npm run build` in `web-ui`: production compile, lint, and type check passed.
- Fresh Docker images built for sidecar, backend, and frontend. All three services
  became healthy at `localhost:25801`, `localhost:25800`, and `localhost:7860`.

## Live local runtime

- GPU: NVIDIA GeForce RTX 4090.
- Sidecar-reported VRAM during the Docker check: 23,030 MiB total, 21,463 MiB free.
- `/api/edit/capabilities`: official name `Mage-Flow-Edit`; exact Base, aligned,
  and Turbo Microsoft repositories; `available=false`; no verified checkpoint
  revisions configured; no fallback.
- `huggingface-access-audit.json`: current CLI plus an authenticated browser recheck
  confirms 401/404 for the exact repositories, no Mage-Flow-Edit gated request, and
  no edit checkpoint in Microsoft's live Mage collection. No credential is recorded.
- The empty-state screenshots show the truthful unavailable boundary.
- The staged screenshots use the legacy mock editor only to exercise responsive
  compare/history/action layout. Both views label it **diagnostic fixture**, state
  that it is not Mage-Flow-Edit output, and disable approve/retry/branch/publish.

## Independent validation

An independent validator reviewed the desktop/mobile screenshots, Studio IA,
supported controls, runtime/VRAM state, queue semantics, provenance, API, and
Cloudflare gates. The first review found incomplete public decision-manifest linkage,
missing drag/drop handlers, a binary queue badge, and incomplete state screenshots.
Those findings were fixed and re-reviewed. Final result: **PASS for draft PR readiness**.

The validator explicitly confirms this is **not release-ready for real inference**:
the official checkpoints remain inaccessible, so there is no genuine edit output or
RTX 4090 Turbo/aligned latency and peak-memory benchmark.

## Cloudflare endpoint

Read-only checks returned HTTP 200 from
`https://dreamgen.agenticinsights.com/` and `/api/images`. The API response carried
release `20260731-96377d84c54dbd25`; all 336 records had a release ID and a
content-versioned image URL. See `cloudflare-endpoint.json` and
`cloudflare-headers.txt`. No asset or release pointer was modified.
