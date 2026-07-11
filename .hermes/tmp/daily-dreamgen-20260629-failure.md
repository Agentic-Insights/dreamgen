## Daily DreamGen RTX 4090 generation failure (2026-06-29)

Scheduled daily check-in attempted real generation because no `image_20260629_*.png` existed under `output/2026/week_*`.

### Environment / diagnostics

Command:

```bash
uv run --active dreamgen diagnose
```

Relevant output:

```text
PyTorch Version: 2.6.0+cu124
✓ CUDA available (version 12.4)
  - GPU 0: NVIDIA GeForce RTX 4090 (22.5 GB)
Memory: 19.1 GB available / 63.8 GB total (70.1% used)
Issues Detected
1. Low disk space on output (26.4 GB free)
2. Low disk space on logs (26.4 GB free)
3. Low disk space on .cache (26.4 GB free)
4. Ollama not found in PATH. Required for prompt generation.
```

### Attempt 1: Z-Image

Command:

```bash
uv run --active dreamgen generate --backend zimage --prompt "June 29 2026 daily DreamGen: a luminous RTX 4090 generative-art observatory where neural brushstrokes become constellations, inspired by current AI image-generation discourse about faster local creative tools; cinematic cyber-organic architecture, iridescent glass, precise composition, vivid volumetric light, optimistic morning briefing energy"
```

Output target was announced:

```text
Saving output to: output\2026\week_27\image_20260629_090131_a48033ac.png
Loading Z-Image model from: ckpts\Z-Image-Turbo
Device: cuda
Attention backend: _sdpa
Loading Z-Image from: ckpts\Z-Image-Turbo
Loading DiT...
bash: [1052: 2 (255)] tcsetattr: Inappropriate ioctl for device
ELAPSED_SECONDS=6
PEAK_GPU_MEMORY_MB=2038
```

Process exited with code `139`. It wrote only the prompt metadata file:

```text
output/2026/week_27/image_20260629_090131_a48033ac.txt
```

No matching `.png` was created.

### Attempt 2: FLUX fallback

Command:

```bash
uv run --active dreamgen generate --backend flux --prompt "June 29 2026 daily DreamGen fallback: a luminous RTX 4090 generative-art observatory where neural brushstrokes become constellations, inspired by current AI image-generation discourse about faster local creative tools; cinematic cyber-organic architecture, iridescent glass, precise composition, vivid volumetric light, optimistic morning briefing energy"
```

Failure:

```text
File "...diffusers\models\model_loading_utils.py", line 196, in load_state_dict
    if f.read().startswith("version"):
       ^^^^^^^^
MemoryError
Generation failed
Backend: flux
Phase: image generation
Error: Failed after 2 attempts:
ELAPSED_SECONDS=34
PEAK_GPU_MEMORY_MB=2050
```

It wrote only the prompt metadata file:

```text
output/2026/week_27/image_20260629_090156_18c4800b.txt
```

No matching `.png` was created.

### Expected behavior

If CUDA/RTX 4090 is available, either Z-Image should complete successfully or fail with a captured Python-level diagnostic instead of exit `139`. If FLUX cannot load due to host memory pressure, the CLI should include actionable memory guidance and avoid leaving prompt-only artifacts that look like partial successful outputs.

### Duplicate search performed

```bash
gh issue list --state all --search 'Z-Image segfault exit 139 DiT load'
gh issue list --state all --search 'FLUX MemoryError load_state_dict'
```

Both returned no results.
