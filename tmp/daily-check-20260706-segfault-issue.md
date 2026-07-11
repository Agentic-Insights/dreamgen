## Summary
Daily scheduled DreamGen RTX 4090 check on 2026-07-06 found CUDA/RTX 4090 available, but both real backends crashed with Windows process exit `-1073741819` / bash exit `139` before writing a PNG. Prompt metadata `.txt` files were created, but matching `.png` files were missing.

## Environment
- Repo: https://github.com/Agentic-Insights/dreamgen
- Local path: `C:\Users\vaski\projects\dreamgen`
- Branch/status: `main...origin/main` with local modifications in `AGENTS.md`, `web-ui/app/globals.css`, `web-ui/app/page.tsx`, plus untracked `.hermes/`
- Last commit: `d0beb7a 2026-06-21 09:07:06 -0500 Merge pull request #65 from Agentic-Insights/codex/desktop-probe-console-ux`
- Python: 3.11.10
- PyTorch: `2.6.0+cu124`
- CUDA available: yes, CUDA 12.4 from PyTorch
- GPU: `NVIDIA GeForce RTX 4090 (22.5 GB)`
- `ckpts\Z-Image-Turbo`: exists
- System memory at diagnose: `9.7 GB available / 63.8 GB total (84.8% used)`

## Diagnose output excerpt
```text
GPU Support
✓ CUDA available (version 12.4)
  - GPU 0: NVIDIA GeForce RTX 4090 (22.5 GB)
✗ MPS not available

Issues Detected
1. Low disk space on output (138.1 GB free)
2. Low disk space on logs (138.1 GB free)
3. Low disk space on .cache (138.1 GB free)
4. Ollama not found in PATH. Required for prompt generation.

Summary
✓ System has NVIDIA GPU with CUDA support
! 4 issues detected
```

## Prompt used
```text
July 6, 2026 daily DreamGen: a luminous generative-art poster inspired by X AI artists sharing glowing butterfly dreamscapes and Japan Send AI Art Exhibition theme of love; an androgynous stargazer in a dark abstract summer sky, translucent iridescent butterflies forming a heart-shaped constellation, subtle glitch light leaks, cinematic digital-dream atmosphere, elegant anime-meets-surreal editorial composition, rich blues violets and warm gold, ultra detailed, hopeful and collaborative
```

## Reproduction: Z-Image
Command:
```powershell
Set-Location "C:\Users\vaski\projects\dreamgen"
uv run --active dreamgen generate --backend zimage --prompt "<prompt above>"
```

Output excerpt:
```text
Using image backend: zimage (resolved: zimage, requested: zimage)
Image generation: request submitted to zimage
Saving output to: output\2026\week_28\image_20260706_090210_b6605928.png
2026-07-06 09:02:10.525 | INFO | src.generators.zimage_generator:_load_native_components:168 - Loading Z-Image model from: ckpts\Z-Image-Turbo
2026-07-06 09:02:10.525 | INFO | src.generators.zimage_generator:_load_native_components:169 - Device: cuda
2026-07-06 09:02:10.526 | INFO | utils.loader:load_from_local_dir:110 - Loading DiT...
EXIT_CODE=-1073741819
ELAPSED_SECONDS=12.1
NVIDIA_SMI_AFTER:
NVIDIA GeForce RTX 4090, 2591 MiB, 23028 MiB, 16 %
/usr/bin/bash: line 3: 29024 Segmentation fault powershell.exe ...
```

Observed files:
- Created prompt metadata: `C:\Users\vaski\projects\dreamgen\output\2026\week_28\image_20260706_090210_b6605928.txt` (491 bytes)
- Missing expected PNG: `C:\Users\vaski\projects\dreamgen\output\2026\week_28\image_20260706_090210_b6605928.png`

## Fallback attempted: FLUX
Command:
```powershell
Set-Location "C:\Users\vaski\projects\dreamgen"
uv run --active dreamgen generate --backend flux --prompt "<prompt above>"
```

Output excerpt:
```text
Using image backend: flux (resolved: flux, requested: flux)
Image generation: request submitted to flux
2026-07-06 09:02:49,632 - src.generators.image_generator - INFO - Using NVIDIA GPU: NVIDIA GeForce RTX 4090
Saving output to: output\2026\week_28\image_20260706_090249_b6605928.png
2026-07-06 09:02:49,699 - src.generators.image_generator - INFO - Loading model from black-forest-labs/FLUX.1-schnell
Loading checkpoint shards:   0%|          | 0/3 [00:00<?, ?it/s]
EXIT_CODE=-1073741819
ELAPSED_SECONDS=22.8
NVIDIA_SMI_AFTER:
NVIDIA GeForce RTX 4090, 2562 MiB, 23028 MiB, 8 %
/usr/bin/bash: line 3: 29037 Segmentation fault powershell.exe ...
```

Observed files:
- Created prompt metadata: `C:\Users\vaski\projects\dreamgen\output\2026\week_28\image_20260706_090249_b6605928.txt` (491 bytes)
- Missing expected PNG: `C:\Users\vaski\projects\dreamgen\output\2026\week_28\image_20260706_090249_b6605928.png`

## Expected
If a native backend crashes, DreamGen should surface a clear backend failure and not leave the daily check looking partially successful. Ideally, diagnostics should also capture whether this is a CUDA/PyTorch/driver/native-extension crash.

## Actual
Both backends crash the process before image creation. Only `.txt` prompt metadata files are written.

## Duplicate search performed
```text
gh issue list --state all --search "Z-Image segmentation fault DiT loading exit 139"
gh issue list --state all --search "segmentation fault generation exit 139"
```
Both searches returned no results.
