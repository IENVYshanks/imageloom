# Benchmarks

Measured with ImageLoom 1.0 on a **base MacBook/Mac mini M4 (10-core GPU, 16 GB RAM)**, Metal backend, one image per job, model already on disk.
"Seconds" is wall time reported by the job (includes loading the model). Your numbers will differ; the app learns them per model and size and uses them for its estimates.

## Create

| Model | 512² | 768² | 1024² | 1536² |
|---|---|---|---|---|
| Qwen-Image 2.1 Turbo Q8 (8 steps) | 110 s | 239 s | 395 s | 1882 s (31 min, banding rings in smooth skies) |
| Z-Image Turbo Q4_K (8 steps) | 84 s | 151 s | ~250 s (extrapolated) | not measured |

Peak memory for Qwen-Image 2.1 Turbo Q8 was about 9 GB while creating, so a 16 GB Mac swaps if Xcode, simulators or a browser with many tabs compete for RAM. 2048² was never run
(~95 min extrapolated).

## Edit (Qwen-Image 2.1 Turbo Q8)

Editing feeds the photo into the model as extra tokens, so it is much slower than creating and the effort ladder uses smaller sizes.

| Size | Time | Peak memory |
|---|---|---|
| 512² | 152 s | ~10.4 GB |
| 768² | 1208 s (20 min, swapping) | ~10.5 GB |

## Upscale (Real-ESRGAN family via `sd-cli -M upscale`)

| Input → output | `quality` (RealESRGAN x4plus) | `fast` (4xNomos2 MoSR) |
|---|---|---|
| 1024² → 4096² | 245 s | 38 s |
| 512² → 3840² | 64 s | 11 s |

Peak memory is about 0.5 GB. `fast` leaves a woven pattern on smooth areas (sky, backgrounds, foam) that is clearly visible at 100%, so use it for drafts only.

**Recipe that works well on 16 GB:** render a 512-768 px draft (1.5-4 min), then upscale the keeper to 4K with `quality` (about 1 min per input megapixel × 4).

## Contribute your numbers

Open a discussion or a model request with: chip + RAM, model + quantization, size, seconds, and peak memory if you measured it.
