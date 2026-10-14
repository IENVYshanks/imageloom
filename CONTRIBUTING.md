# Contributing to ImageLoom

Thanks for helping! ImageLoom is deliberately small: a pure-stdlib Python server, one HTML file for the UI, and thin native hosts. Please keep it that way
(no new runtime dependencies without a very good reason, no build step for the UI).

## Where help is most welcome

- **Windows testing.** The installer and portable build are assembled on a Mac and have never been run on Windows. Reports (even "it starts") are gold.
- **Linux.** The server already knows the Vulkan engine release; nobody has tried it yet.
- **New model families** in [`core/models.py`](core/models.py): each family is a recipe (CLI flags, required files, defaults, effort levels). See [docs/MODELS.md](docs/MODELS.md).
- **Translations.** The UI ships English and Russian; adding a language is one dictionary in `core/web/index.html`.
- **Measured timings** for your hardware (see [docs/BENCHMARKS.md](docs/BENCHMARKS.md)).
- Code signing / notarization setup for the macOS and Windows builds.
- Anything under the [good first issue](../../labels/good%20first%20issue) label.

## Development setup

```bash
git clone https://github.com/elapen/imageloom && cd imageloom
python3 -m venv .venv && source .venv/bin/activate
pip install -r core/requirements.txt ruff
IMAGELOOM_HOME=/tmp/imageloom-dev python3 core/server.py     # UI at http://127.0.0.1:7870, the first-run wizard downloads engine + models
python3 -m unittest discover -s tests -v                      # offline, never runs the engine
ruff check core tests
```

`IMAGELOOM_HOME` points the server at a throw-away data folder so development never touches your real models and history. Other variables:
`IMAGELOOM_PORT`, `IMAGELOOM_SD_CLI` (use your own `sd-cli`), `IMAGELOOM_ENGINE_DIR`.

Build the apps locally (no CI needed): `./mac/build.sh` (macOS, needs Xcode command line tools) and `./windows/build_windows.sh` (cross-builds the Windows
installer on a Mac; needs `makensis`). See [docs/BUILDING.md](docs/BUILDING.md).

## Pull requests

1. Open an issue first for anything bigger than a small fix, so we agree on the direction.
2. Keep the change focused; match the surrounding style (concise code, comments only where the *why* is not obvious).
3. Add or update a test when you touch the server or `models.py`. Tests must stay offline and must not run `sd-cli`.
4. UI strings go through the i18n layer (English source text + Russian entry). Check both languages and a 375 px wide window.
5. If you add a model recipe, say what you actually ran: model, quant, hardware, resolution, time. Untested recipes are marked "experimental" in the UI.
6. By contributing you agree that your work is released under the MIT license.

## Reporting bugs

Use the bug template and include: OS and chip, RAM, ImageLoom version (`imageloom status`), the model, the size you asked for, and the tail of
`<data folder>/logs/server.log`. For crashes while generating, the `sd-cli` output in that log is what matters.
