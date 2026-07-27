# Microsoft Mage-Flow evaluation

DreamGen recognizes **Microsoft Mage-Flow** as a local text-to-image backend.
It is not a Microsoft video generator. The sibling Mage-VL model understands
images and video; Mage-Flow generates and edits images.

## Verified upstream facts

- Official source: <https://github.com/microsoft/Mage>
- Official checkpoint: <https://huggingface.co/microsoft/Mage-Flow>
- Turbo checkpoint: <https://huggingface.co/microsoft/Mage-Flow-Turbo>
- Paper: <https://arxiv.org/abs/2607.19064>
- Release: Microsoft lists the six generation/edit checkpoints as released on
  July 22, 2026.
- License: the source repository and the Hugging Face model card identify MIT.
- Availability: `microsoft/Mage-Flow` is public and ungated. Its current
  checkpoint is about 17.5 GB across 43 files.
- Featured checkpoint: the 20-step RL-aligned model at revision
  `faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9`. DreamGen pins this revision
  instead of following a moving branch. The 4-step Turbo checkpoint remains an
  explicit speed-oriented alternative, not the default quality probe.
- Scope: Microsoft describes the family as research-only and not intended for
  product or service deployment. That is compatible with DreamGen's local model
  probing purpose, but it must remain visible to operators.
- Tested runtime: Python 3.10+, Torch 2.13, torchvision 0.28, Diffusers 0.38,
  Transformers 5.5, and CUDA. Microsoft's accelerated path uses FlashAttention;
  the isolated DreamGen runtime selects upstream's slower Torch SDPA fallback.
  Triton also needs a C compiler at runtime, so the sidecar includes and reports
  the native build toolchain instead of claiming readiness without it.
- Hardware: Microsoft reports about 18–20 GB peak GPU memory at 1024² on one A100.
  DreamGen therefore uses a conservative 20 GB VRAM readiness guard.

Microsoft's published text-to-image table reports Mage-Flow ahead of
Z-Image-Turbo on GenEval, TIIF, and CVTG-2K, while Z-Image-Turbo remains stronger
on several Chinese/long-text scores. These are author-reported results, not a
DreamGen-controlled benchmark, so the current model identity and parameters are
always stored with each artifact.

## DreamGen backend comparison

| Backend | Local role | Readiness / tradeoff |
| --- | --- | --- |
| Mage-Flow | Preferred research renderer when ready | Public 4B BF16 checkpoint; native 512–2048 resolution; isolated 20 GB+ CUDA runtime; upstream research-only guidance |
| Z-Image-Turbo | Current high-quality local path and LoRA experiments | 6B, eight-step renderer; requires the complete local checkpoint and either native source or DiffSynth for LoRAs |
| FLUX.1 Schnell | Established transformer fallback | Selected by `auto` only when cached; larger model and existing DreamGen CUDA path |
| Small SD (`segmind/tiny-sd`) | Safe first-run fallback | Public and much lighter, capped to 512 in DreamGen; useful but substantially less capable |
| Qwen-Image NF4 | Typography-oriented specialist | Quantized/offloaded path for text-rich and bilingual layouts; higher cache/memory cost |
| ERNIE-Image-Turbo | Multilingual prompt-enhanced specialist | Eight-step local Diffusers path; prompt enhancement can reduce strict comparability |
| SD Turbo | Explicit fast renderer | Four-step, 512-class output path |
| Smoke / Mock | Diagnostics only | Clearly labeled non-production probes; never presented as Mage-Flow output |

## DreamGen runtime policy

Mage-Flow runs in a dedicated local Docker sidecar. This prevents its newer
Torch and Transformers requirements from changing the established Z-Image,
FLUX, Qwen, ERNIE, Turbo, and Small SD environment. Its optional host review
port binds to `127.0.0.1`; other machines cannot submit generation or download
requests through that port.

`IMAGE_BACKEND=auto` selects Mage-Flow only when:

1. the exact configured public checkpoint is fully present in the shared
   Hugging Face cache;
2. the sidecar is reachable and reports CUDA plus at least 20 GB VRAM; and
3. the sidecar reports the same model ID and a compatible runtime.

Otherwise `auto` retains the existing FLUX-then-Small fallback. An explicit
`IMAGE_BACKEND=mageflow` request fails clearly if readiness disappears; it is
never relabeled as a successful Mage-Flow render.

The upstream content-policy gate returns a plain white image for both policy
refusals and classifier failures. DreamGen screens before generation and turns
that condition into an explicit error with the upstream category and reason, so
a blank refusal cannot be cataloged as a successful render.

DreamGen's **Unload** control delegates to the sidecar and serializes unload
against generation, so the operator can truthfully release Mage-Flow's VRAM
before switching to another heavyweight backend.

## Local validation

The Docker review used an RTX 4090 with 22.49 GiB VRAM, Torch
`2.13.0+cu130`, SDPA, model revision
`faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9`, and Microsoft source revision
`6cefeb40e4c8ecc404ecb73732a91878939f27e0`. The Mage-Flow subtree is unchanged
between the original evaluation commit and this latest verified upstream
revision; the intervening commits only update Mage-VL documentation. A 512²,
20-step warm generation
through `ImageGenService` completed in 4.74 seconds and retained exact text in
the test scene. The smoke request used `add_to_gallery=False`.

## Configuration

```dotenv
MAGEFLOW_MODEL=microsoft/Mage-Flow
MAGEFLOW_MODEL_REVISION=faca09c18c1c19458e7fbc3f7bce6f7a7d4d01a9
MAGEFLOW_URL=http://mageflow:8001
MAGEFLOW_STEPS=20
MAGEFLOW_CFG=5.0
MAGEFLOW_TIMEOUT_SECONDS=1800
MAGEFLOW_ATTENTION=sdpa
MAGEFLOW_MIN_VRAM_GB=20
MAGEFLOW_PORT=25801
```

Download the public checkpoint from **Settings → Models**. After the card says
`READY`, select **Mage-Flow** or **Auto**. The first render loads the model into
the sidecar; `loaded` is reported separately from cached/runtime readiness.
