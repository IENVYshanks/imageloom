# Third-party notices

ImageLoom's own code is MIT-licensed (see [LICENSE](LICENSE)). It uses, bundles in its release builds, or downloads at run time the
components below. They keep their own licenses; please read them before redistributing or using results commercially.

## Bundled in the release builds (installers, DMG, portable zip)

| Component | Role | License |
|---|---|---|
| [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) (`sd-cli`, official release binaries, sha256-checked at build time) | inference engine (Metal on macOS, Vulkan on Windows) | MIT |
| [CPython](https://www.python.org/) via [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | embedded runtime | PSF License (plus the permissive licenses of its bundled libraries) |
| [Pillow](https://python-pillow.org/) | thumbnails, WebP/PNG/JPEG export | MIT-CMU (HPND) |
| [Send2Trash](https://github.com/arsenetar/send2trash) | move files to the Trash/Recycle Bin | BSD-3-Clause |
| [vtracer](https://github.com/visioncortex/vtracer) | raster to SVG tracing | MIT |
| [pywebview](https://github.com/r0x0r/pywebview), pythonnet, clr_loader, cffi, pycparser, bottle, proxy_tools (Windows build only) | native window around the UI | BSD-3-Clause / MIT (each package ships its own LICENSE file inside the bundle) |

## Downloaded at run time (never redistributed by this repository)

Model weights and encoders are fetched from Hugging Face on the user's request. Each model has its own license; the add-model dialog and
`imageloom models add --dry-run` show the license reported by the repository.

| Model | Used for | License (check the model card, it is the authority) |
|---|---|---|
| Qwen-Image 2.1 Turbo, GGUF conversions by [AtomicChat](https://huggingface.co/AtomicChat), VAE from [Comfy-Org](https://huggingface.co/Comfy-Org) | default model: create, edit, transparent backgrounds | Qwen Research License (research / non-commercial) |
| The default text encoder is a variant of Qwen3-VL with the refusal behaviour removed ("abliterated") | prompts for the default model | see the AtomicChat model card |
| [Z-Image Turbo GGUF](https://huggingface.co/leejet/Z-Image-Turbo-GGUF), [Qwen3-4B-Instruct-2507 GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF), FLUX `ae` VAE | optional faster model | Apache-2.0 |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) `RealESRGAN_x4plus`, `RealESRGAN_x4plus_anime_6B` | upscaling ("quality", "illustration") | BSD-3-Clause |
| `4xNomos2_hq_mosr` by Philip Hofmann (Phhofm) | upscaling ("fast") | CC-BY-4.0 |

Images you generate are your own output, but some model licenses restrict how outputs may be used (for example non-commercial terms).
That is between you and the model's license; ImageLoom does not change it.

## Icon

The application icon was generated locally with ImageLoom itself (Qwen-Image 2.1 Turbo) and is released under the project's MIT license.
