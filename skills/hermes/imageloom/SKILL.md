---
name: imageloom
description: "Local image generation, editing, upscaling and export (PNG/WebP/SVG, transparent backgrounds) via the imageloom CLI: Qwen-Image 2.1 Turbo or any model added from a Hugging Face link; a 768 px create takes ~4 min on a base 16 GB M4, an edit at 512 px ~2.5 min."
version: 1.0.0
platforms: [macos, windows, linux]
metadata:
  hermes:
    tags: [image, generation, editing, qwen, stable-diffusion-cpp, local, creative]
    related_skills: [comfyui, claude-design]
---
# imageloom: local image generation, editing, upscaling and export (Qwen-Image 2.1 Turbo Q8, no refusals, + Real-ESRGAN)

Runs fully on the local machine (timings below were measured on a base Apple M4 with 16 GB; other hardware differs, the app learns real timings per model) through stable-diffusion.cpp (`sd-cli`, Metal). The default model is 8-bit (Q8_0):
`Qwen-Image-2.1-Turbo-Q8_0.gguf` (denoiser, AtomicChat), `Qwen-Image-2.1-Turbo-Abliterated-Uncensored-Q8_0.gguf` (Qwen3-VL text encoder with the refusal
direction removed, AtomicChat), `mmproj-...-F16.gguf` (vision, needed for editing), `qwen_image_2.1_vae_bf16.safetensors` (Comfy-Org).
Results land in `~/Pictures/ImageLoom/`. Strengths: photorealism, long natural-language prompts, readable text inside images (English verified; clean block-letter
Cyrillic verified), instruction editing that keeps the rest of the picture intact.

## Create

```bash
imageloom "a vintage travel poster of the Swiss Alps, bold retro lettering reading 'SWISS ALPS'"
```

Prints the absolute path of each finished PNG on stdout (progress goes to stderr). Add `--json` for `{images, seeds, seconds, peak_gb, ...}`.

| Flag | Meaning |
|---|---|
| `-q fast` (default) | ~768 px, **~4 min** (measured 239 s). |
| `-q standard` | ~1024 px, **~6.6 min** (measured 395 s). |
| `-q hq` | ~1536 px, **~31 min** (measured 1882 s). Fine detail, but smooth skies can show banding rings. Only on explicit request. |
| `-q max` | ~2048 px, ~95 min (extrapolated, never run). Only if the user insists. |
| `-s 512x512` | exact `WxH`: both divisible by **32**, 512..2752, width*height <= 2048*2048. 512x512 takes ~1.8 min: good for drafts. |
| `-r 16:9` | aspect ratio (`1:1 4:3 3:4 16:9 9:16 3:2` ...), default `1:1`. |
| `-n 4` | several variants from one model load; each extra image costs ~30 s less than the first. |
| `--seed N` | reproducible result; keep the seed and tweak a few words to iterate on a composition. |
| `-m ID` | pick an installed model by id or part of its name (see Models). |
| `--transparent` | transparent background (real alpha channel; see Formats). |
| `-o path.png` | also copy the result to a project path (for `-n >1` adds `-1`, `-2`, ...). `--open` opens it in Preview. |

## Models: switch, or add a new one from a Hugging Face link

```bash
imageloom models                                              # list: id, status, size, [edit, alpha, experimental]; * = default
imageloom "a red fox" -m z-image                              # use another installed model for this job (id or part of the name)
imageloom models add https://huggingface.co/owner/repo --dry-run   # inspect: family, weights files, companions, warnings; nothing downloaded
imageloom models add https://huggingface.co/owner/repo [--file X.gguf] [--family z-image] [--name N]   # download + register, waits and prints progress
imageloom models use ID | imageloom models rm ID
```

- The CLI default is **the model chosen in the app**, so pass `-m` explicitly whenever the model matters.
- `models add` reads the repo through the Hugging Face API, recognises the family (Qwen-Image 2.1, Z-Image, FLUX.1, SDXL, SD 1.5; "other" = manual), picks the best weights
  file that fits 16 GB, and downloads what the family needs (text encoder, VAE, CLIP...) with resumable downloads. Files already on disk are skipped. Always run `--dry-run`
  first for an unknown repo and tell the user the size. Gated repos (e.g. black-forest-labs/FLUX.1-*) need a Hugging Face token (the add-model dialog asks for it and stores it locally).
  Diffusers-format repos (folders of shards) are not readable by `sd-cli`: look for a GGUF or a single .safetensors file.
- Only **Qwen-Image 2.1 Turbo Q8 is verified** on a base M4, and only it can **edit** photos and draw **transparent** backgrounds. Z-Image Turbo Q4_K (optional) was also tested end to end
  (measured: a 768 px photo of a fox in 151 s vs 239 s for Qwen at the same size, 1024 px estimated ~4 min, create only). FLUX/SDXL/SD1.5 recipes come from the stable-diffusion.cpp docs and are untested: say so if you use one. Each model has its own time estimates; "(оценка)" in the app = not measured yet,
  after the first job the server learns the real time.

## Edit an existing image

```bash
imageloom edit photo.jpg "replace the sky with a dramatic sunset, keep everything else the same"
imageloom edit portrait.png "make the jacket red" -q standard
imageloom edit logo.png "remove the background" --transparent -o cutout.png
```

Any format macOS can read works (`sips` converts it). The result keeps the input's aspect ratio. Up to 3 inputs: add `-i extra.png` (extra references, e.g. "put the
person from image 2 into image 1"). Editing is **much slower than creating** because the photo becomes part of the computation, so its tiers are smaller:

| `-q` | size | time (base M4, 16 GB) |
|---|---|---|
| `fast` (default) | ~512 px | **~2.5 min** (measured 152 s) |
| `standard` | ~640 px | ~8 min (interpolated) |
| `hq` | ~768 px | **~20 min** (measured 1208 s, memory swaps) |
| `max` | ~1024 px | ~1.5 h (extrapolated, avoid) |

The output has the edit tier's resolution (e.g. 512 px), not the original's. For a local change on a large photo, the app's brush tool pastes the edited area
back into the full-resolution original (see below); from the CLI you only get the whole re-rendered image.
Good edit instructions are plain sentences: what to change, plus "keep everything else the same". Changing text works ("change the headline to 'ALPES'").
Edit needs an edit-capable model; the CLI picks one automatically if the default cannot edit.

## Formats and transparency: PNG, WebP, SVG

The model always writes PNG. Convert or vectorize afterwards:

```bash
imageloom export picture.png --format webp [-q 90 | --lossless] [-o out.webp]    # also png, jpeg
imageloom export logo.png --format svg --preset logo|illustration|detailed|bw   # traces to real vector paths (vtracer); transparency kept
imageloom "a red fox logo, flat vector style, plain background" --transparent -o fox.png   # real alpha channel, then export to webp/svg
```

- `--transparent` wraps the prompt so Qwen draws an RGBA image; the server then checks the pixels for real alpha (the result is flagged "прозрачный"). Only the Qwen-Image 2.1 model
  supports it; re-run with a new `--seed` if the background came out opaque. PNG and WebP keep the alpha; JPEG cannot.
- SVG is a **tracing** of the raster, great for logos, icons and flat illustrations (few colours); photos become large, noisy files. Start with `--preset logo`, ask for "flat vector style,
  plain background, few colours" when you plan to vectorize. Default SVG max side is 1536 px.

## Upscale (make a small result 2x / 4x / 4K / 8K)

AI upscaling (Real-ESRGAN family, `sd-cli -M upscale`, runs on the GPU, only ~0.5 GB of memory) is far cheaper than rendering large: a 512 px draft (110 s)
plus a 4K upscale (seconds to minutes) beats rendering 1536 px natively (31 min).

```bash
imageloom upscale picture.png --to 4k                       # long side 3840 px (default model: quality)
imageloom upscale photo.jpg --to 2x --model fast -o big.png
imageloom "a red fox in snow" -s 512x512 --upscale 4k       # create small, then auto-upscale (also works with `imageloom edit ... --upscale 4k`)
```

| `--to` | result |
|---|---|
| `2x`, `4x` | that multiple of the input |
| `2k`, `4k`, `8k` | long side 2560 / 3840 / 7680 px (limit 8192 px on the long side) |

| `--model` | what it is | time (base M4, 16 GB) |
|---|---|---|
| `quality` (default) | Real-ESRGAN x4plus: clean, even result | ~245 s per megapixel of INPUT (1024 px -> 4096 px took 4 min) |
| `fast` | 4xNomos2 MoSR: 6x faster but leaves a visible woven pattern on smooth areas (sky, backgrounds, foam), clearly seen at 100% after big enlargements: **drafts only, never finals** | ~38 s per megapixel of INPUT |
| `illustration` | Real-ESRGAN x4plus anime 6B: posters, drawings, anime | ~100 s per megapixel (estimate) |

Everything is a 4x network; `2x` / `2k` / `4k` are then resized to the exact target. Upscaling sharpens and cleans but cannot invent true detail, so judge the
composition at small size first and upscale only the keeper. Always use `quality` for anything delivered (tested on a 512 px source taken to 4K: `quality` was clean, `fast` showed the weave). The 4K PNG is 20-40 MB. The original stays as the
"before" version; `imageloom upscale` prints the new file path.

## The app and its UI (for the user)

**ImageLoom** (the desktop app (a native window, no browser)) starts its own server when opened and stops the server and any running render when quit;
`imageloom ui` opens the same studio in a browser tab (http://127.0.0.1:7870). It is a chat-style studio: **separate chats**, each remembering its own **model and effort level**
(a ChatGPT/Claude-style model picker and an effort picker next to the prompt; effort = target size, and the step count for base models), ⌘K command palette, ⌘N new chat,
**add a model by pasting a Hugging Face link**, conversational editing (a result becomes the next photo to edit with one click), drag and drop or ⌘V to add photos,
**brush mask** (paint the area, describe the change, the edited pixels are pasted only into the painted area of the full-resolution original), before/after slider,
version branches, one-click upscale (x2/x4/2K/4K/8K) and an auto-upscale option, export to PNG/WebP/SVG with a transparent-background switch, gallery with favourites, quick
style and edit chips, live time estimates, a warning before heavy sizes, desktop notification when done, shortcuts (`?`).
Agents use the CLI; the app, the browser tab and the CLI share one server and one queue. Releases: `~/Projects/imageloom-studio/dist/` (macOS DMG; a Windows installer exists but was not run on Windows; neither is code-signed).

## How to run it from an agent

- Jobs take minutes. **Do not block on a default-timeout shell call.** Run in the background (or raise the timeout to the maximum) and read the printed path when
  it finishes. One job runs at a time; extra jobs queue. Draft with `-s 512x512` first, then render the final size.
- Look at the result before you report it: open the PNG with your image-capable file reader and check it matches the request (spelled text, anatomy);
  regenerate with a new `--seed` or a sharper prompt if not.
- Tell the user the real path; put the file inside the project when it is a project asset (`-o assets/hero.png`).
- **Memory: peak ~9 GB creating, ~10.5 GB editing** (measured) on a 16 GB machine, so macOS swaps if Xcode, Simulators or big builds run at the same time. Do not
  start heavy jobs alongside it. Sizes above `fast` (create) or 512 px (edit) ask the user first, because of the waiting time.
- Never start a model download without telling the user its size; `imageloom models add ... --dry-run` prints it.

## Prompting Qwen-Image

- Write a scene, not keywords: subject, setting, lighting, lens/medium, mood, composition ("close-up", "wide shot", "top-down").
- Put exact text in single quotes and say where it is and how it looks: `a neon sign reading 'RAMEN'`, `white block letters 'Доброе утро' on a wooden sign`.
  Keep text to a few short words. Fancy handwriting is the least reliable (an early Cyrillic chalkboard test came out garbled); always check the output.
- Name the medium or style (`35mm photo`, `flat vector illustration`, `watercolor`, `isometric 3D render`, `mid-century poster`).
- Turbo is distilled: it always runs **8 steps, guidance 1.0, with the checkpoint's own sigma schedule**. There is no negative prompt and no CFG knob;
  steer by describing what you want. Stay at 512 px or more.

## Behaviour and limits

- **No safety filter anywhere in this stack** (the diffusion model has none, and the text encoder is the abliterated one), so apply your own judgment and the
  usual content rules for what you generate or edit for the user. Other models the user adds have their own licenses (the add dialog shows them).
- Weights of the default model are under the Qwen Research License (research / non-commercial). Mention this if the user plans commercial use.
- Upscaler weights live in `models/upscale/` (three .pth files, ~97 MB; official Real-ESRGAN releases and Phhofm's 4xNomos2_hq_mosr, CC-BY). Not wired in: img2img strength (`-i`), `--mask` inpainting in `sd-cli`, video (`-M vid_gen`, impractical at 16 GB).
- `imageloom doctor` checks the engine, the model files and the three upscalers. Everything lives in the data folder (macOS `~/Library/Application Support/ImageLoom`, Windows `%LOCALAPPDATA%\ImageLoom`, Linux `~/.local/share/imageloom`): `engine/` or `sd/bin/` (the `sd-cli` binary), `models/<id>/` per model, `models/_shared/` for shared encoders and VAEs, `models/upscale/`, `models.json` (registry), `chats.json`, `history.jsonl`, `logs/server.log`.
- If `doctor` reports missing files, re-download from Hugging Face: `AtomicChat/Qwen-Image-2.1-Turbo-GGUF` (Qwen-Image-2.1-Turbo-Q8_0.gguf),
  `AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF` (Qwen-Image-2.1-Turbo-Abliterated-Uncensored-Q8_0.gguf and mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-F16.gguf),
  `Comfy-Org/Qwen-Image-2.1` (vae/qwen_image_2.1_vae_bf16.safetensors).

## Hermes notes

- Run `imageloom` through the terminal tool in the background; it takes several minutes, so tell the user the expected wait first (e.g. "~4 min", edits "~2.5 min").
- Deliver the finished picture with `MEDIA:<absolute path>` on its own line so Telegram and other gateways attach it. To edit a photo the user sent, pass its local path to `imageloom edit`.
