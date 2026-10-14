"""Shared test plumbing: a throwaway data folder, the real server module imported against it, no network, no sd-cli.

Import this before anything else in a test module. Nothing here (or in the tests) ever starts `sd-cli`: the process
launcher is replaced by a tripwire, and the network opener refuses every connection unless a test installs its own.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

HOME = Path(tempfile.mkdtemp(prefix="imageloom-test-"))
DATA = HOME / "data"
OUT = HOME / "pictures"
DATA.mkdir()
(DATA / "config.json").write_text(json.dumps({"output_dir": str(OUT)}), encoding="utf-8")

# The server reads its folders at import time, so the environment must be ready first.
os.environ["IMAGELOOM_HOME"] = str(DATA)
for _k in ("IMAGELOOM_SD_CLI", "IMAGELOOM_ENGINE_DIR", "IMAGELOOM_PORT", "IMAGELOOM_PARENT_PID"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(CORE))

import models as M  # noqa: E402
import server  # noqa: E402

NO_ENGINE = HOME / "no-engine" / "sd-cli"  # never exists
server.find_sd_cli = lambda: NO_ENGINE  # (a real sd-cli on this machine's PATH must not change what the tests see)


def _tripwire(*_a, **_k):
    raise AssertionError("a test tried to start sd-cli")


server.spawn = _tripwire


class _NoNetwork:
    def open(self, req, *a, **k):
        raise AssertionError(f"a test tried to use the network: {getattr(req, 'full_url', req)}")


M.OPENER = _NoNetwork()
WARNINGS: list[str] = []  # what models.warn() would have printed to stderr
M.warn = WARNINGS.append


def cleanup() -> None:
    shutil.rmtree(HOME, ignore_errors=True)


import atexit  # noqa: E402

atexit.register(cleanup)


# ----------------------------------------------------------------------------------------- helpers
def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fake_hf(routes: dict):
    """A stand-in for models.hf_json: `routes` maps a path prefix (after /api/models/) to a fixture file name."""
    def hf_json(path, token=None, timeout=40):
        for prefix, name in routes.items():
            if path.startswith("/api/models/" + prefix):
                return fixture(name)
        raise ValueError(f"repository not found (no fixture for {path})")
    return hf_json


def png_bytes(w: int = 4, h: int = 4, color=(10, 200, 30), noise: bool = False, dims=None) -> bytes:
    """A real PNG built with the standard library only. `noise` makes it incompressible (big file); `dims` lies in the header."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    row = (lambda: b"\x00" + os.urandom(3 * w)) if noise else (lambda r=b"\x00" + bytes(color) * w: r)
    raw = b"".join(row() for _ in range(h))
    iw, ih = dims or (w, h)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", iw, ih, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


class Reply:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return json.loads(self.body)

    def __repr__(self):
        return f"Reply({self.status}, {self.body[:120]!r})"


class LiveServer:
    """The real HTTP server of server.py on a random free port, in a thread."""

    def __enter__(self):
        self.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self._old_port = server.CFG["port"]
        server.CFG["port"] = self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.CFG["port"] = self._old_port

    def request(self, method: str, path: str, body: bytes | dict | None = None, headers: dict | None = None, host: str | None = None, post_header: bool = True) -> Reply:
        """One request; `host` overrides the Host header, POSTs carry X-ImageLoom unless `post_header` is False."""
        hdrs = dict(headers or {})
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        if method == "POST" and post_header:
            hdrs.setdefault("X-ImageLoom", "1")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host if host is not None else f"127.0.0.1:{self.port}")
            for k, v in hdrs.items():
                conn.putheader(k, v)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            r = conn.getresponse()
            return Reply(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
        finally:
            conn.close()

    def get(self, path: str, **kw) -> Reply:
        return self.request("GET", path, **kw)

    def post(self, path: str, body=None, **kw) -> Reply:
        return self.request("POST", path, body if body is not None else {}, **kw)

    def raw(self, data: bytes, timeout: float = 5.0) -> bytes:
        """Send raw bytes on a fresh connection and return whatever comes back before the server closes it."""
        s = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        try:
            s.sendall(data)
            out = b""
            while True:
                try:
                    chunk = s.recv(65536)
                except (TimeoutError, ConnectionResetError):
                    break
                if not chunk:
                    break
                out += chunk
            return out
        finally:
            s.close()


def symlinks_work() -> bool:
    probe = HOME / "_probe_link"
    try:
        os.symlink(str(HOME), str(probe))
    except (OSError, NotImplementedError):
        return False
    probe.unlink()
    return True
