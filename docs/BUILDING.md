# Building the apps

Releases are built **locally** (no CI required). Both scripts download pinned, checksum-verified inputs into `.cache/` the first time and reuse them afterwards.

## macOS (Apple Silicon): `ImageLoom.app` + DMG

```bash
VERSION=1.0.0 ./mac/build.sh        # -> dist/ImageLoom.app and dist/ImageLoom-1.0.0-macOS-arm64.dmg
```

Needs: Xcode command line tools (`swiftc`), `python3` with Pillow (for the icon step), the GitHub CLI `gh` (to look up the latest `stable-diffusion.cpp` release, or set
`IMAGELOOM_ENGINE_DIR` to a folder with `sd-cli` + `libstable-diffusion.dylib`), network.

Steps: compile the Swift shell (`mac/Sources/main.swift`: AppKit + WKWebView, menus, notifications, save panel) → embed python-build-standalone → install
`core/requirements.txt` into it → copy `core/` → download and verify the engine → build the `.icns` from `assets/icon_1024.png` → write `Info.plist` and ad-hoc sign → DMG.
The app is **ad-hoc signed only**: macOS asks the user to approve it (right-click → Open, or System Settings → Privacy & Security → Open Anyway). With an Apple Developer ID you can
replace the `codesign --sign -` line and add notarization.

## Windows (x64): installer + portable zip, cross-built on macOS

```bash
VERSION=1.0.0 ./windows/build_windows.sh     # -> dist/ImageLoom-1.0.0-Windows-x64-Setup.exe and ...-portable.zip
```

Needs: `makensis` (`brew install makensis`), `curl`, `unzip`. The script downloads the embedded Windows Python and the `win_amd64` wheels (resolved by hand, `--no-deps`),
the Vulkan `sd-cli` release, assembles the tree, and compiles the NSIS installer (`windows/installer.nsi`: per-user install without admin rights, Start Menu and Desktop shortcuts,
VC++ runtime check, uninstaller). The window is pywebview on WebView2, falling back to Edge `--app`.

> **Not verified on real Windows yet.** Everything is assembled and compiled on a Mac. Please report what you see. The installer is unsigned, so SmartScreen will warn.

## Running from source instead

```bash
pip install -r core/requirements.txt
python3 core/server.py        # http://127.0.0.1:7870; the first-run wizard fetches the engine and the default model
./core/imageloom --help
```

## Checksums

After building, `shasum -a 256 dist/*` and paste the output into the release notes.
