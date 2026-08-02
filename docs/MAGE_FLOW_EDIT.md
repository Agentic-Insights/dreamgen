# Microsoft Mage-Flow-Edit in DreamGen

DreamGen calls the feature **Mage-Edit** and records the official model family name,
**Microsoft Mage-Flow-Edit**, on every derivative. It never presents another editor,
mirror, or fixture as Mage-Flow-Edit.

## Pinned primary source

- Implementation: `https://github.com/microsoft/Mage`
- Reviewed source commit: `6cefeb40e4c8ecc404ecb73732a91878939f27e0`
- Source license and Mage-Flow license declared by Microsoft: MIT
- Intended-use caveat: Microsoft's README says the models are for research purposes,
  are not intended for product/service deployment, and require human oversight and
  downstream moderation, validation, and compliance safeguards.
- Required runtime behavior retained by DreamGen: Microsoft's multimodal content gate
  and Gaussian-Shading watermark are not optional or bypassed.

Official checkpoint repositories:

| Variant | Repository | Official edit default |
| --- | --- | --- |
| Base | `microsoft/Mage-Flow-Edit-Base` | 30 steps, CFG 5 |
| RL-aligned | `microsoft/Mage-Flow-Edit` | 30 steps, CFG 5 |
| Turbo | `microsoft/Mage-Flow-Edit-Turbo` | 4 steps, CFG 1 |

The pinned root checkpoint table and edit benchmark both list the aligned edit model
at 30 steps. A generic parameter note in the same source says “RL 20”; that value also
appears for the text-to-image RL model. DreamGen follows the edit-specific table and
benchmark and keeps the user free to change steps.

## Availability boundary (checked 2026-08-01)

Anonymous Hugging Face API, resolve, and git requests return HTTP 401. The local
Hugging Face CLI is not authenticated. More importantly, a signed-in browser session
shows HTTP 404 for all three official edit repositories, and Microsoft's live Mage
collection no longer lists them. No standard gated-model agreement or request-access
control is offered.

This distinguishes the current state from an ordinary license gate: the repositories
are withdrawn, private, or otherwise unavailable to this account. Therefore DreamGen
ships edit inference disabled. Full official checkpoint commit SHAs and file hashes are
intentionally blank; abbreviated search-index revisions and community copies are not
accepted as proof.

Exact recovery action: Microsoft must restore/publicize the three repositories, or the
operator must use a Hugging Face account that Microsoft has explicitly granted access.
Then run `hf auth login` in the local terminal, verify each official repository resolves,
pin its full 40-character commit SHA in the corresponding `MAGEFLOW_EDIT_*_REVISION`
variable, and set `MAGEFLOW_EDIT_ENABLED=true`. Never paste a token into logs or source.

## Supported operation

The official API accepts one natural-language instruction plus one or more reference
images and returns one edited image. It was trained with up to three references, though
the implementation accepts more. Supported categories include semantic/local content
editing; subject, scene, and camera transformations; appearance and artistic changes;
conditional reconstruction/restoration; and multi-reference composition.

DreamGen exposes only official parameters: command, seed, steps, CFG, maximum output
side (512–2048), optional negative prompt, and the 384-pixel visual-language condition
edge. Output dimensions remain multiples of 16. There is no model-supported edit
`strength` control, so the Mage-Edit Studio and CLI do not expose one.

## RTX 4090 boundary and evidence

The supported baseline is one RTX 4090-class NVIDIA GPU with 24 GB VRAM or better.
The checked host reports an RTX 4090 with 23,028 MiB total VRAM. Microsoft's published
measurement is approximately 18–20 GB peak and 1.02 seconds for Turbo at 1024² on an
A100; it is context, not DreamGen's 4090 benchmark.

No official edit checkpoint was accessible, so no truthful RTX 4090 edit latency,
peak-memory measurement, or visual output can be reported yet. DreamGen does not call
CPU/offload or another editor a successful Mage-Edit fallback. The sidecar serializes
generation/edit work, unloads the previous model before switching, reports measured
elapsed time and peak CUDA allocation, and rejects execution until an official full
revision is configured and cached. Turbo and aligned must both be benchmarked on the
4090 before this integration is release-ready.

## Immutable lineage and publication

Each session writes a content-addressed normalized source under
`output/edits/<root>/source`, version-addressed derivatives under `versions`, and
append-only hash-linked creation/decision manifests under `manifests`. Jobs retain the
command, source/derivative SHA-256, official model and revisions, settings, parent/root
IDs, version, timing, GPU/VRAM evidence, and decision.

Edit sources and pending/rejected derivatives are not publishable. Approval is a
separate immutable decision record. Only an approved, non-diagnostic derivative can be
moved to `published`/`featured` and enter Cloudflare release-manifest schema v2. Release
items carry edit lineage, content-versioned URLs, the source catalog hash, and rollback
links to the previous release. Publishing never deletes remote or local assets by
default.
