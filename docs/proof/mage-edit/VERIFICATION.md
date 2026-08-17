# Mage-Flow-Edit verification record

Rechecked on 2026-08-16 from `codex/mage-edit-studio`, based on current `main`
after PR #72 merged. PR #73 remains draft and unmerged.

## Mirror and runtime

- Artifact source: `Comfy-Org/Mage-Flow` at exact revision
  `dbba082792fb61234d7218327511a9725b69db37`.
- Boundary: this is an explicitly user-authorized mirror, not a proven Microsoft-owned
  canonical successor. Every runtime response and immutable manifest records both the
  Comfy artifact source and the Microsoft upstream identity.
- Loaded artifacts passed byte-size and SHA-256 validation. The aligned and Turbo
  transformer hashes match the earlier independently inventoried community duplicates.
- Only JSON/tokenizer layout metadata comes from
  `mage-flow-community/Mage-Flow-Edit@fd7119d80fff2e5be21178edf2a93877955540b9`;
  no community weight shard is used. The Comfy encoder contains all 713 expected keys.
- Microsoft runtime source remains pinned to
  `76bec2bb3818863f470de7e867c2dc7f1d0bfd83`; SDPA, the content gate, and watermark
  are retained.

## Genuine RTX 4090 edits

All results below came from the fresh Docker Mage sidecar on an NVIDIA GeForce RTX 4090
with 23,028 MiB total VRAM. They are model output, not fixtures.

| Evidence | Variant | References | Inference | Peak VRAM | Output SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| `aligned-single-dog.png` | aligned, 30 steps / CFG 5 | 1 | 6.5671 s | 17,426 MiB | `98e4b6bda160e2c8e337a3362388dd96dbf3bb0882f0c8b28f2a5daec30e63af` |
| `aligned-multiref-headphones.png` | aligned, 30 steps / CFG 5 | 2 | 6.5592 s | 17,432 MiB | `8656d53a920879733aa84a83a489c1bd5bd470acfee31f5281a135903dd35a39` |
| `turbo-single-dog.png` | Turbo, 4 steps / CFG 1 | 1 | 3.6262 s | 17,426 MiB | `15da4b0cf3f60045a442d9791700c09944ca56ce0cfa4359ae36409b9bf8a36a` |
| `turbo-1024-dog.png` | Turbo, 4 steps / CFG 1, 1024 | 1 | 2.5640 s | 17,431 MiB | `023a5d419dfc9f2fbc6848ffa61560263cb50df5ade7e9effb2c9e9d09b6dece` |

Cold HTTP totals, including model construction and first load, were 123.13 seconds for
aligned and 93.64 seconds for Turbo. The warm two-reference aligned request completed in
7.43 seconds. Response-header captures preserve mirror/upstream/config revisions, artifact
paths and hashes, Microsoft source SHA, elapsed time, and peak VRAM.

The final hash-enforcing sidecar recheck reproduced the Turbo 512 output byte-for-byte.
Warm 1024, 1536, and 2048 probes completed in 2.5640, 3.7565, and 5.9665 seconds with
17,431, 17,548, and 18,292 MiB peak CUDA allocation. System free VRAM narrowed to 1,743,
568, and 356 MiB respectively. Studio keeps 1024 as the measured default, labels 1536
tight and 2048 experimental, and the sidecar rejects 4096 with HTTP 422 before inference;
no fallback is attempted.

The single-reference outputs add the requested red scarf while preserving the dog, pose,
lighting, and background. The two-reference output transfers the turquoise clip from the
second source onto the black headphone headband from the first while retaining the yellow
product-photo setting.

## Automated and Docker checks

- Full suite: **163 passed, 1 skipped**; two existing FastAPI `on_event` deprecation
  warnings. The previously environment-dependent Ollama test now uses a deterministic
  prompt fixture.
- Focused API/capability/sidecar suite: **52 passed**.
- `black --check` and `isort --check-only`: clean across `src`, `tests`, and
  `mageflow-service`.
- Next.js production build: compile, lint, type check, and static generation passed.
- Fresh Docker sidecar/backend/frontend images built. All three became healthy at
  `localhost:25801`, `localhost:25800`, and `localhost:7860`; API status, model status,
  edit capabilities, and Studio were checked on those ports.
- `studio-edit-real-desktop*.png` and `studio-edit-real-mobile*.png` capture the genuine
  result, responsive setup/compare/action views, 4090 state, exact mirror provenance,
  and history from that fresh build.
- Independent final re-review: **PASS — release-ready draft**. The validator independently
  checked output hashes, the four-entry retry lineage chain, desktop/mobile UX, measured
  4090 boundaries and pre-inference 4096 rejection, and the approval-gated gallery plan.
  This pass does not authorize merge.
- Pylint's errors-only pass reports the optional local `zimage` package and the isolated
  sidecar-only `mage_flow` package as unavailable in the host development environment;
  both imports resolve in their intended runtimes, and no other error is reported.

## Lineage and Cloudflare gate

The API/CLI store ordered normalized source hashes, derivative hash, exact mirror and
upstream identities, artifact/config revisions and hashes, command/settings, timing,
VRAM/GPU, root/parent/version, and immutable decision records. Diagnostic jobs cannot be
approved. Pending and rejected edits cannot enter a Cloudflare release plan. Approval is
explicit and append-only; publishing uses content-versioned URLs and rollback metadata
and never deletes local or remote assets by default.

The public API job `f00aaa2b-3e06-4a3d-a817-4ff19817b7cf` reproduced the direct Turbo
result byte-for-byte (`15da4b0c…8a36a`), recorded 3.9840 seconds / 17,426 MiB, and wrote
a three-entry immutable chain: source registration, derivative creation, and explicit
approval. Its local catalog state was then set to `published` solely to exercise the
dry-run gate; no remote publish was executed.

The CLI job `679d152a-db6f-45ab-ac0a-66b2d7128869` made a second genuine command-driven
edit in 3.1961 seconds / 17,430 MiB and printed the Comfy mirror revision, Microsoft
upstream identity, artifact path/SHA-256, manifest, and pending/local decision state.
Its royal-blue scarf result remains pending. The Cloudflare dry run explicitly skips
that pending derivative and both immutable sources.

Recovered Studio jobs now visibly hydrate their immutable command and controls. Retry
is server-authoritative: it re-hashes each immutable stored source and submits the selected
job's exact saved command, variant, seed, steps, CFG, size, negative prompt, and
visual-language edge rather than current form defaults. A deterministic API lineage test
asserts that the retry is version 2 under the same root and its settings object is
byte-for-byte equivalent to version 1.

The recovered-session Studio proof then exercised that endpoint through the freshly built
Docker UI. Real v2 job `39a41685-fded-477d-beed-0a9d3c8ab460` retained v1's root, source
hash, Turbo/seed 43/4-step/CFG 1/512 settings, and pending decision state. It completed in
4.4656 seconds at 17,426 MiB peak after a 220-second cold integrity-check/load path and
reproduced v1 byte-for-byte (`f44b589f…746b`). `studio-edit-retry-v2.png` and
`retry-v2-job.json` preserve the UI and API evidence.

The refreshed local dry run reports one approved image, four upload objects (image,
prompt, metadata, decision manifest), 17 skipped assets, and zero deletions. It skips both
pending blue-scarf versions with `state=draft`. The existing public gallery and `/api/images` endpoint
were checked read-only on 2026-08-16: both returned HTTP 200 through Cloudflare, the API
served 336 records and release header `20260731-96377d84c54dbd25`. No asset or release
pointer was modified.
