# Microsoft Mage-Flow-Edit in DreamGen

DreamGen calls the feature **Mage-Edit** and records both identities on every
derivative: Microsoft's upstream model family and the exact repository that supplied
the bytes. It never relabels another editor or a diagnostic fixture as Mage-Flow-Edit.

## Sources and pinned revisions

- Upstream implementation: `https://github.com/microsoft/Mage`
- Reviewed source commit: `76bec2bb3818863f470de7e867c2dc7f1d0bfd83`
- Checkpoint mirror authorized by this DreamGen operator: `Comfy-Org/Mage-Flow`
- Mirror revision: `dbba082792fb61234d7218327511a9725b69db37`
- Diffusers layout/tokenizer metadata only: `mage-flow-community/Mage-Flow-Edit`
  at `fd7119d80fff2e5be21178edf2a93877955540b9`
- License declared by Microsoft and the mirror card: MIT.
- Intended-use caveat: Microsoft's README says the models are for research purposes,
  not product/service deployment, and require human oversight, moderation, validation,
  and compliance safeguards.
- Microsoft's multimodal content gate and Gaussian-Shading watermark remain enabled.

Microsoft's three original Hugging Face repositories remain unavailable to anonymous
requests and to the checked signed-in account. `Comfy-Org/Mage-Flow` describes itself as
"Repackaged model files for ComfyUI" and links Microsoft's source. This is not evidence
that Microsoft transferred canonical ownership. The operator explicitly authorized this
mirror; DreamGen therefore labels it `user_authorized_comfy_org_mirror` and preserves the
Microsoft upstream identity separately.

The aligned and Turbo transformer hashes in the Comfy repository exactly match the
previously audited `mage-flow-community` duplicates. No community weight shards are
loaded. The aligned community repository supplies only the missing Diffusers JSON and
tokenizer text metadata; a key inventory check found 713 expected and 713 present text
encoder tensors, with no missing or unexpected keys.

| Lane | Upstream identity | Mirror artifact | SHA-256 | Default |
| --- | --- | --- | --- | --- |
| Base | `microsoft/Mage-Flow-Edit-Base` | `diffusion_models/mage_flow_edit_base_bf16.safetensors` | `9d93faa75963ba4a2ef1b64bed4fe94c2554b82e8f3fb2dbb267604a634d450d` | 30 steps, CFG 5 |
| Aligned | `microsoft/Mage-Flow-Edit` | `diffusion_models/mage_flow_edit_bf16.safetensors` | `09cee4afa95239d850af02c9b1c006bffc71dca4a984a2a1f56edff9282d53d3` | 30 steps, CFG 5 |
| Turbo | `microsoft/Mage-Flow-Edit-Turbo` | `diffusion_models/mage_flow_edit_turbo_bf16.safetensors` | `29c3726ecd64afe149eef28af3e27b6b40de52646bfd16757a37da4b6fbcf288` | 4 steps, CFG 1 |

Aligned and Turbo are downloaded and verified. Base remains an available selectable
lane but is not cached. The shared Qwen3-VL BF16 encoder is 8,875,719,384 bytes with
SHA-256 `36f3ff447ef59201722e8f9ce6020c9819fdcfba6aa2608c4e09b1c0ce114e34`;
the BF16 VAE is 345,053,056 bytes with SHA-256
`34e076dc1e8a15321e1e07be5111d59cf16dd10b804b7c7e20b4de29013427e0`.
DreamGen builds a no-copy Diffusers overlay from links to those pinned blobs.

## Supported operation

The API accepts one instruction plus one to three reference images and returns one
edited image. The output aspect ratio follows the primary reference. Retry reuses the
complete reference set; branch-from-result starts a new single-primary iteration.
Supported categories include local/semantic edits, subject/scene/camera transforms,
appearance and artistic changes, restoration, and multi-reference composition.

Studio exposes command, variant, seed, steps, CFG, maximum output side (512–2048),
optional negative prompt, and the 384-pixel visual-language condition edge. There is no
model-supported edit `strength`, so DreamGen does not expose one.

## RTX 4090 evidence

The supported baseline is one RTX 4090-class NVIDIA GPU with 24 GB VRAM or better. The
Docker sidecar measured these genuine edits on the checked RTX 4090 (23,028 MiB total),
using SDPA and a 512-pixel maximum side:

| Variant / references | Seed | Inference | Peak CUDA allocation | Cold HTTP total |
| --- | ---: | ---: | ---: | ---: |
| Aligned / one | 42 | 6.5671 s | 17,426 MiB | 123.13 s |
| Aligned / two | 7 | 6.5592 s | 17,432 MiB | 7.43 s (warm) |
| Turbo / one | 42 | 3.6262 s | 17,426 MiB | 93.64 s |
| Turbo / one, 1024 max side | 42 | 2.5640 s | 17,431 MiB | 3.17 s (warm) |
| Turbo / one, 1536 max side | 42 | 3.7565 s | 17,548 MiB | 4.50 s (warm) |
| Turbo / one, 2048 max side | 42 | 5.9665 s | 18,292 MiB | 7.09 s (warm) |

The shipped 1024 default is therefore measured on the baseline card. System-reported free
VRAM after each request was approximately 1,743 MiB at 1024, 568 MiB at 1536, and only
356 MiB at 2048 after Windows display overhead. All exposed sizes completed for this
portrait source, but Studio labels 1536 as tight and 2048 as experimental because other
aspect ratios and concurrent GPU use can change the margin. A 4096 request is rejected
before inference with HTTP 422; no substitute backend or offload path runs. DreamGen
serializes work, shows load/free/peak VRAM, and unloads the previous variant before
switching. It does not call CPU offload or another editor a successful Mage-Edit fallback.

Proof inputs, outputs, response headers, hashes, and the mirror audit are under
`docs/proof/mage-edit/`.

## Immutable lineage and publication

Each session writes content-addressed normalized sources under
`output/edits/<root>/source`, version-addressed derivatives under `versions`, and
append-only hash-linked creation/decision manifests under `manifests`. Jobs retain the
ordered source hashes, command, derivative hash, mirror and upstream identities,
artifact/config revisions and hashes, settings, parent/root IDs, version, timing,
GPU/VRAM evidence, and decision.

Sources and pending/rejected derivatives are not publishable. Approval is a separate
immutable decision record. Only an approved, non-diagnostic derivative can enter the
Cloudflare release-manifest v2 pipeline. Release items carry lineage, content-versioned
URLs, source catalog hash, and rollback links. Publishing never deletes remote or local
assets by default.
