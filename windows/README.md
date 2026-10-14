# ImageLoom for Windows

The Windows build of the same app: an embedded Python 3.13, the `core/server.py` server, a window on WebView2 (pywebview) and the
stable-diffusion.cpp engine (`sd-cli.exe`, Vulkan build). It installs without administrator rights, into the user profile.

## NOT TESTED ON WINDOWS

**This build was cross-compiled on macOS and has never been run on Windows.** There is not a single "installed, opened,
generated an image" check. All that has been verified, on a Mac:

- `python3 -m py_compile windows/app.py` and `bash -n windows/build_windows.sh`;
- the logic of `app.py` (port, single instance, starting and stopping the server, close confirmation, the Edge fallback) was exercised on
  a Mac with a stub in place of the server and a stub in place of pywebview, that is, without Windows, without WebView2 and without the
  real `server.py`;
- the installer and the zip build, and the installer contents were inspected with `7zz l` (python, site-packages, engine, `app/`);
- every `.exe`/`.dll`/`.pyd` inside is PE x86-64; the Python wheels are `win_amd64`/`cp313`/`any`.

What has **not** been verified and may not work on the first try:

- starting under `pythonw.exe`: pywebview 6.2.1 + pythonnet 3.2.1 + clr_loader 0.3.1 on Python 3.13, the window on WebView2;
- the installer pages, the shortcuts, the "Apps" entry, the uninstaller, and the WebView2 and VC++ Redistributable checks and downloads;
- `sd-cli.exe` on a particular graphics card through Vulkan (driver, VRAM, speed);
- paths with Cyrillic characters (the user name): `sd-cli.exe` reads its command line as UTF-16 (judging by its imports), but this was not tried;
- how SmartScreen and Windows Defender react to unsigned files.

If the WebView2 window does not come up, the app opens itself in Microsoft Edge (`msedge --app=`); the reason is written to the log.

## Language

The installer is bilingual (English and Russian) and uses the Windows UI language, falling back to English. The app window has the same
two languages: it follows the system language at first start and can be switched in the help dialog (the `?` button), in the sidebar
or from the command palette (Ctrl+K).

## Building (on a Mac)

```bash
./windows/build_windows.sh              # version 1.0.0
VERSION=1.2.0 ./windows/build_windows.sh
```

You need: Homebrew (the script installs `makensis` itself if it is missing), `.venv/bin/python` with Pillow, pip (or `uvx`), `curl`,
`unzip`, `zip` and internet access. The script downloads and caches in `.cache/`: Python (python-build-standalone, Windows x64), the wheels
(`pip download --platform win_amd64`) and the engine (the latest leejet/stable-diffusion.cpp release, `bin-win-vulkan-x64.zip`, the sha256 is
checked). The build tree is `.build/windows`, the results go to `dist/`:

- `ImageLoom-Studio-<version>-Windows-x64-Setup.exe`: the installer (NSIS, English and Russian);
- `ImageLoom-Studio-<version>-Windows-x64-portable.zip`: the same tree plus `ImageLoom.bat`.

The Windows dependencies are listed by hand in `core/requirements.txt` and `windows/requirements-host.txt` (the wheels are downloaded with `--no-deps`).

Note: `makensis` 3.13 aborts with `std::bad_alloc` when it runs in the plain `C` locale; run the build with a UTF-8 locale
(for example `LC_ALL=en_US.UTF-8`).

## Installing

1. Run `Setup.exe`. It installs into `%LOCALAPPDATA%\Programs\ImageLoom` and creates shortcuts in the Start menu and on the desktop.
2. The installer checks for the Microsoft Visual C++ Redistributable 2015-2022 x64 (version 14.40 or newer is required, the engine will not
   start without it) and for the WebView2 Runtime. If either is missing it offers to download and install it (internet access is needed,
   and Windows may ask for administrator approval).
3. On first launch the setup wizard inside the app downloads the models (about 18 GB, from Hugging Face) into the data folder.

Portable version: unpack the zip and run `ImageLoom.bat` (the data still goes to `%LOCALAPPDATA%\ImageLoom`; to keep it next to the app,
uncomment the `set IMAGELOOM_HOME` line in the `.bat`). The portable version does not check dependencies: install the VC++
Redistributable (x64, 14.40 or newer) and WebView2 yourself.

## Requirements

- Windows 10 or 11, x64 (ARM64 is not supported);
- a graphics card with a Vulkan driver (NVIDIA, AMD or Intel, with an up-to-date driver);
- 16 GB of RAM recommended;
- about 25 GB of free disk space: models ~18 GB, the app ~0.3 GB, plus room for images and downloads.

## SmartScreen

The installer is not signed, so Windows shows "Windows protected your PC". Click **More info → Run anyway**.
The same may happen for the app itself and for Windows Defender.

## WebView2

The app window uses the Microsoft Edge WebView2 Runtime. Windows 11 and most up-to-date Windows 10 systems already have it.
If it is missing, the installer offers to install it. Without it the app opens in Edge in app mode (or in the default browser);
in that case closing the window does not stop the program: use the "Quit ImageLoom" button in the help dialog.

## Where things live

- data (models, history, thumbnails, `config.json`, the window profile): `%LOCALAPPDATA%\ImageLoom`;
- log (server and launcher): `%LOCALAPPDATA%\ImageLoom\logs\server.log` (the previous one is `server.old.log`);
- finished images: `Pictures\ImageLoom`;
- launching the app again while it is running opens one more window to the same server and does not stop it when that window closes.

Uninstalling: "Settings → Apps". The data (models ~18 GB) is kept by default; the uninstaller asks about it separately (the default is "No").
Images in `Pictures\ImageLoom` are never deleted.

## Known limitations

- there is no auto-update; when installing over an older version the app must be closed (the installer will ask);
- the installer is built with `RequestExecutionLevel user`: it does not install into `Program Files` or "for all users";
- the `core/imageloom` command-line tool is not part of the build (in error messages `imageloom doctor` is not available; the setup wizard in the app replaces it).
