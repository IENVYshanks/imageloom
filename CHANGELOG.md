# Changelog

All notable changes to ImageLoom. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [1.0.0] - 2026-10-14

First public release.

### Added
- Native macOS app (Apple Silicon, Swift + WKWebView, embedded Python) with a DMG; the server starts with the app and stops, with any running job, when it quits.
- Experimental Windows installer and portable zip (cross-built on macOS, **not yet run on real Windows**).
- Chat-style studio: separate chats, each with its own model and effort level; every result can become the next input; command palette (`⌘K`), new chat (`⌘N`).
- Create, edit by instruction, brush-mask edit (only painted pixels are pasted into the full-resolution original), before/after slider, version tree, favourites, gallery.
- Upscale ×2 / ×4 / 2K / 4K / 8K with Real-ESRGAN (quality / fast / illustration), optionally chained after every render.
- Export to PNG, WebP, JPEG and SVG (vtracer presets); real transparent backgrounds with Qwen-Image.
- Model manager: add a model from a Hugging Face link (family detection, file picker with sizes, companion files, resumable downloads, disk-space check, optional token for gated repos).
- Models: Qwen-Image 2.1 Turbo Q8 (default, verified), Z-Image Turbo Q4_K (verified); FLUX.1, SDXL and SD 1.5 recipes (experimental).
- Time estimates that learn real timings per model and size.
- CLI (`imageloom`): create, edit, upscale, export, `models add|use|rm`, and ready-made skills for Claude Code, Cursor and Hermes.
- English and Russian UI (auto-detected, switchable), also for the macOS and Windows hosts and the Windows installer.
- Security hardening and a 181-test offline suite (guard, path traversal, redirects that must not leak the token, archive extraction, corrupt state files).
