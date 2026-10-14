# Security policy

ImageLoom runs a small HTTP server on `127.0.0.1` (default port 7870) for its own window, browser tab and CLI. It is not meant to be exposed to a
network, and it refuses to bind anywhere else.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's private reporting instead:
**Security tab → "Report a vulnerability"** (Private vulnerability reporting). Include the version (`imageloom status`), your OS, and steps to reproduce.
You will get an answer within a week; fixes are released as soon as they are verified, and reporters are credited unless they prefer otherwise.

## What is in scope

- anything that lets a web page or another local user drive the server without the `X-ImageLoom` header / localhost Host check (CSRF, DNS rebinding),
- reading, writing or deleting files outside the output and data folders (path traversal, symlinks, archive extraction),
- command or argument injection into `sd-cli` or OS helpers,
- leaking the optional Hugging Face token (it is stored in the file `hf_token` (mode 0600) in the data folder and must only ever be sent to huggingface.co),
- anything in the build scripts that could ship an unverified binary.

## Known trade-offs

- The release builds are not code-signed or notarized (macOS shows a Gatekeeper prompt, Windows shows SmartScreen). Verify the SHA-256 listed in the
  release notes against your download.
- The server has no user accounts: everyone who can reach `127.0.0.1:7870` on your machine can use it. Do not forward the port.
- Model files are downloaded from Hugging Face over HTTPS. GGUF/safetensors files are data, not code, but you are still trusting the publisher.
