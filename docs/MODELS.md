# Models

ImageLoom runs any model that [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) can run, as long as it has a **family recipe**.
You never edit a config file: paste a Hugging Face link and the app does the rest.

## Add a model from a link

*App:* the model picker (next to the prompt) → **Add model by link**, or `⌘K` → "Add model…".
*CLI:* `imageloom models add https://huggingface.co/owner/repo` (add `--dry-run` first to see the plan).

What happens:

1. The app reads the repository through the Hugging Face API (public repos need no account; for gated repos paste a token, it stays on your computer and is only sent to huggingface.co).
2. It detects the **family** (Qwen-Image 2.1, Z-Image, FLUX.1, SDXL, SD 1.5, or "other") and the variant (turbo / base / schnell / dev). You can override both.
3. It lists the weight files (GGUF or single `.safetensors`) with sizes and marks the recommended one: the largest quantization that comfortably fits a 16 GB machine.
4. It adds the **companion files** the family needs (text encoder, VAE, CLIP, …), skipping what is already on disk, and checks free disk space.
5. It downloads with resume support, registers the model, and it appears in the picker. Each chat remembers its own model.

Warnings you may see: gated repository (token needed), Diffusers-format repository with folders of shards (`sd-cli` cannot read it; look for a GGUF or single-file build),
a file that is too large for 16 GB.

## Support status

| Family | Create | Edit | Transparent | Status |
|---|---|---|---|---|
| **Qwen-Image 2.1 Turbo** (default, Q8) | yes | yes (instruction + brush) | yes | **verified** on Apple M4 16 GB |
| **Z-Image Turbo** (Q4_K GGUF) | yes | no | no | **verified** end to end on Apple M4 16 GB |
| FLUX.1 (schnell / dev) | yes | no | no | experimental: recipe from the sd.cpp docs, not run by the author |
| Stable Diffusion XL | yes | no | no | experimental |
| Stable Diffusion 1.5 | yes | no | no | experimental |
| Other | manual | no | no | you set files and flags |

"Experimental" means the command line follows the upstream documentation but nobody has confirmed it on real hardware yet. If you run one, please open a
[model request](../../../issues/new?template=model_request.yml) with the model, quantization, hardware and time, so it can be marked verified.

## Effort levels

The picker next to the prompt offers four **effort** levels per model (Fast / Balanced / Quality / Max). For distilled "turbo" models the step count is fixed by the model and
effort only changes the image size; for base models it also changes the number of steps. Sizes and measured times for the verified models are in [BENCHMARKS.md](BENCHMARKS.md).

## Adding a family (for contributors)

A family is a dictionary in [`core/models.py`](../core/models.py): which `sd-cli` flag takes which file (`--diffusion-model`, `--llm`, `--vae`, …), required and optional
companion files with their repositories, per-variant defaults (steps, CFG, sampler, sigmas), the size multiple and limits, capabilities (`edit`, `alpha`, `text`),
the effort ladder, and regular expressions that recognise repository names. Add tests in `tests/test_models.py` with a trimmed Hugging Face tree JSON fixture.
