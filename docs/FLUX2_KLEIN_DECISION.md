# FLUX.2 Klein 4B backend decision

Status: implementation gate defined; dedicated adapter and RTX 4090 benchmark pending.

## Decision

DreamGen's next local default target is the distilled **FLUX.2 [klein] 4B** checkpoint,
`black-forest-labs/FLUX.2-klein-4B`. LongCat-Image and Qwen-Image-Edit-2511 are
separately named benchmark lanes, not aliases, hidden fallbacks, or selectable production
backends. Microsoft Mage-Flow-Edit remains its own unavailable, gated adapter.

The target default is deliberately not active yet. The current `flux` generator uses a
generic FLUX.1-era `DiffusionPipeline` path. FLUX.2 is a new architecture and Klein has a
dedicated `Flux2KleinPipeline`; routing the new checkpoint through the old adapter would
create a misleading model identity and unverified controls.

## Verified upstream identities

| Role | Official repository | Full model revision | License | Operations |
| --- | --- | --- | --- | --- |
| Target default | `black-forest-labs/FLUX.2-klein-4B` | `e7b7dc27f91deacad38e78976d1f2b499d76a294` | Apache-2.0 | generation, single-ref edit, multi-ref edit |
| Benchmark | `meituan-longcat/LongCat-Image` | `d2ea50b79a930074c37b9b97ce45e3b2ea8cf4d8` | Apache-2.0 | generation |
| Benchmark | `Qwen/Qwen-Image-Edit-2511` | `6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9` | Apache-2.0 | single- and multi-reference editing |

Official implementation revisions recorded for reproducibility:

- BFL FLUX.2: `50fe5162777813d869182b139e83b10743caef15`
- Meituan LongCat-Image: `f0e4c43c5ef74b011ff71570fbfc2bdffbc9ab06`
- QwenLM Qwen-Image: `6b5e1f5cec987d404be5ac6657db3b9aacb56a89`
- Diffusers first Klein implementation: `61f175660a8ac54f1470a74a810e6c38fb4795d5`

Primary sources: [BFL model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B),
[BFL inference source](https://github.com/black-forest-labs/flux2),
[Diffusers FLUX.2 docs](https://huggingface.co/docs/diffusers/api/pipelines/flux2),
[LongCat model card](https://huggingface.co/meituan-longcat/LongCat-Image), and
[Qwen edit model card](https://huggingface.co/Qwen/Qwen-Image-Edit-2511).

## Exact FLUX.2 Klein weight evidence

The pinned Hugging Face revision exposes five safetensors files. The root single-file
transformer duplicates the Diffusers transformer component; a pipeline download does not
need both representations.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `flux-2-klein-4b.safetensors` | 7,751,105,712 | `ec3d4e733a771f61c052fb4856c48b336c55eaf2c65487c2a1faeb9bbda7a343` |
| `text_encoder/model-00001-of-00002.safetensors` | 4,967,215,360 | `8c0506e7f4936fa7e26183a4fd8da4e2bdbc5990ba64ae441f965d51228f36ea` |
| `text_encoder/model-00002-of-00002.safetensors` | 3,077,766,632 | `82f2bd839378541b0557bfabaf37c7d3d637071fdcb73302dedd7cf61162ce07` |
| `transformer/diffusion_pytorch_model.safetensors` | 7,751,109,744 | `9f29f9edcfdae452a653ffb51a534ca4decd389952c225724ff3b94042612a6e` |
| `vae/diffusion_pytorch_model.safetensors` | 168,120,878 | `ca70d2202afe6415bdbcb8793ba8cd99fd159cfe6192381504d6c4d3036e0f04` |

LongCat's seven safetensors total 29,293,491,646 bytes. Qwen-Image-Edit-2511's ten
safetensors total 57,699,249,798 bytes. These are download-footprint facts, not VRAM
measurements.

## Controls and 4090 boundary

The distilled Klein defaults are 1024×1024, four steps, and guidance 1.0. Supported
DreamGen controls will be prompt, seed, dimensions, steps, and reference images. No
synthetic edit-strength control will be exposed.

BFL's own official materials currently disagree: the source README says roughly 8 GB
VRAM while the model card says roughly 13 GB. DreamGen therefore makes neither figure a
product guarantee. RTX 4090 / 24 GB is the baseline and `measured_on_target` stays false
until the benchmark captures peak allocated/reserved VRAM, load time, warm/cold latency,
offload mode, dimensions, steps, seed, package commits, output hashes, and GPU/driver data.

## Activation gates

1. Pin a Diffusers revision at or after the first Klein implementation and verify the
   compatible Transformers/PyTorch set in Docker and Windows.
2. Add a dedicated `flux2-klein` adapter for both generation and the provider-neutral edit
   operation. It must always emit the exact model repository and full revision.
3. Download only the official BFL snapshot and verify artifact hashes before loading.
4. Run deterministic 1024px generation, single-reference edit, and multi-reference edit
   on the RTX 4090; capture visual proof and memory/timing provenance.
5. Compare the same prompt families against LongCat generation and Qwen 2511 editing.
6. Only after those gates pass, mark Klein selectable and move `auto` to it. Failures must
   name the actual fallback backend; they must never be reported as Klein output.
