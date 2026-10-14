# Architecture

ImageLoom is three thin layers around one engine. Everything is plain Python standard library and one HTML file, on purpose:
the macOS app is ~160 MB including its own Python, and a fresh checkout needs only Pillow, Send2Trash and vtracer.

```
┌────────────── native host ──────────────┐     ┌──────────── core/server.py ────────────┐     ┌── engine ──┐
│ macOS: Swift + WKWebView (mac/)         │     │ ThreadingHTTPServer on 127.0.0.1:7870  │     │  sd-cli    │
│ Windows: pywebview / Edge --app         │ ──► │ job queue (one job at a time)          │ ──► │ (stable-   │
│ Browser tab / CLI (core/imageloom)      │     │ model registry, downloads, history     │     │ diffusion  │
│ → starts the server, stops it on quit   │     │ export, upscale chains, thumbnails     │     │ .cpp)      │
└─────────────────────────────────────────┘     └────────────────────────────────────────┘     └────────────┘
                     core/web/index.html: the whole UI (vanilla JS, no build step), served by the server
```

## Lifecycle

- The host picks a free port (default 7870), starts `python core/server.py` with `IMAGELOOM_PORT`, `IMAGELOOM_HOST` and `IMAGELOOM_PARENT_PID`, waits for
  `/api/status`, and opens the window. When the app quits (or crashes) the server notices the parent is gone, kills any running `sd-cli` process tree and exits.
- The CLI (`core/imageloom`) discovers the running server through `server.json` in the data folder and starts one on demand.
- A job is one `sd-cli` subprocess. The server builds its command line from the **family recipe** of the chosen model, streams its progress output, registers
  the PNGs in `history.jsonl`, and learns real timings per model and size (`eta_stats.json`) to improve every later estimate.

## Data folders

| What | macOS | Windows | Linux |
|---|---|---|---|
| data (models, history, settings, logs) | `~/Library/Application Support/ImageLoom` | `%LOCALAPPDATA%\ImageLoom` | `~/.local/share/imageloom` |
| images you create | `~/Pictures/ImageLoom` | `Pictures\ImageLoom` | `~/Pictures/ImageLoom` |

Override with `IMAGELOOM_HOME`. Inside the data folder: `models/<id>/` (weights), `models/_shared/` (encoders and VAEs shared by several models),
`models/upscale/` (ESRGAN weights), `engine/` (downloaded `sd-cli`), `models.json` (registry), `chats.json`, `history.jsonl`, `thumbs/`, `logs/server.log`, `config.json`.

## HTTP API (localhost only)

Every POST must carry `X-ImageLoom: 1` and a localhost `Host`/`Origin`; browsers cannot add that header cross-site, which blocks CSRF and DNS-rebinding attacks.

| Route | Purpose |
|---|---|
| `GET /api/status`, `/api/eta`, `/api/history`, `/api/jobs` | state, learned time estimates, gallery rows, running/queued jobs |
| `POST /api/generate` | create / edit / upscale job (`mode`, `prompt`, `width`, `height`, `model`, `effort`, `chat`, `refs`, `transparent`, `then`) |
| `POST /api/cancel` | cancel a job |
| `GET /api/models`, `POST /api/models/inspect|add|delete|active` | model registry and Hugging Face link flow |
| `GET /api/setup`, `POST /api/setup/start|cancel` | first-run wizard (engine, default model, upscalers) |
| `GET/POST /api/chats…` | separate chats with their own model and effort |
| `POST /api/export`, `/api/upload`, `/api/save`, `/api/fav`, `/api/trash`, `/api/reveal` | file operations on the output folder |
| `GET /img/<file>`, `/thumb/<file>?s=` | originals and cached thumbnails |
| `POST /api/quit` | graceful shutdown (used by hosts and `imageloom stop`) |

## Design decisions

- **One job at a time.** A 16 GB machine cannot run two diffusion jobs; the queue makes that explicit instead of swapping the machine to death.
- **Honest ETAs.** Times shown in the UI come from measured runs on the same machine (marked "estimate" until a model has been timed).
- **Sizes divisible by the model's multiple** (32 for Qwen-Image, 16 for Z-Image); the UI snaps and the server validates.
- **Edit by brush** pastes only the edited pixels back into the full-resolution original in the browser, so a 512 px edit pass does not degrade a 4K photo.
- **Resumable downloads** (`.part` files + HTTP Range), shared companion files, a free-disk check before starting.
- **No telemetry.** The only network traffic is Hugging Face and GitHub (engine release) downloads you trigger.

## Security model

The server is meant for one user on one machine, so the goal is "nothing else on the machine, and no web page you visit, can use it":

- Binds to `127.0.0.1` only; every request's `Host` must be a loopback name, and every POST needs the `X-ImageLoom: 1` header plus a loopback `Origin` (no CORS headers are sent, so pages from other sites cannot read responses or send the header).
- Request bodies are capped (JSON 1 MB, uploads 64 MB), connections have timeouts and a concurrency cap, queues, history and thumbnail variants are bounded, and images are decoded only after a header-level size check (decompression bombs).
- File names from clients and from Hugging Face are sanitised; every path is resolved and must stay inside the output or data folder (symlinks included), and only image files are served or trashed.
- Subprocesses run with argument lists (no shell); user text is passed as a value of `-p`, and file names always as absolute paths, so nothing can become a flag.
- Model links accept only `https://huggingface.co/<owner>/<repo>`. The optional token lives in the file `hf_token` (mode 0600), is never returned by the API or logged, and is stripped from cross-host redirects (Hugging Face redirects downloads to CDN hosts).
- Engine archives are verified against the release's sha256 digest and extracted zip-slip-safely into a staging folder.
- The UI page is served with a CSP, `nosniff`, frame denial and a same-origin resource policy.
- Corrupt state files (`config.json`, `models.json`, `chats.json`, `history.jsonl`) are set aside as `*.bad-<time>` and the app starts empty instead of crashing.

The test suite (`tests/`, 181 tests, offline, never runs the engine) covers these behaviours. Trade-off: there are no accounts, so another local user on a shared machine could use the API; see [SECURITY.md](../SECURITY.md).
