"""server.py against the real HTTP server (random port, throwaway data folder): guard, traversal, uploads, settings, limits,
state files, downloads and the engine. Nothing here starts sd-cli or touches the network."""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import _support as S  # noqa: E402
from _support import LiveServer, M, png_bytes, server  # noqa: E402

IS_POSIX = os.name == "posix"
HAS_PIL = server.Image is not None


def out(rel: str = "") -> Path:
    return server.OUT / rel


def put_png(name: str, data: bytes | None = None) -> str:
    p = out(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data or png_bytes())
    return name


@contextlib.contextmanager
def patched(obj, **attrs):
    with mock.patch.multiple(obj, **attrs):
        yield


class Case(unittest.TestCase):
    """Starts one live server per class."""

    live: LiveServer

    @classmethod
    def setUpClass(cls):
        cls.live = LiveServer().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.live.__exit__(None, None, None)


# ----------------------------------------------------------------------------------------- guard
class Guard(Case):
    def test_normal_requests_work(self):
        port = self.live.port
        for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"LOCALHOST:{port}"):
            r = self.live.get("/api/status", host=host)
            self.assertEqual(r.status, 200, host)
            self.assertTrue(r.json()["ok"])

    def test_dns_rebinding_and_odd_hosts_are_refused(self):
        port = self.live.port
        for host in ("evil.com", f"evil.com:{port}", f"127.0.0.1.evil.com:{port}", f"127.0.0.1:{port}.evil.com", f"localhost.evil.com:{port}",
                     f"[::1]:{port}", f"[::ffff:127.0.0.1]:{port}", "127.0.0.1", "localhost", f"127.0.0.1:{port + 1}", f"user@127.0.0.1:{port}", f"127.0.0.1:{port}@evil.com",
                     f"0.0.0.0:{port}", f"2130706433:{port}", f"127.1:{port}", ""):
            with self.subTest(host):
                for method in ("GET", "POST"):
                    self.assertEqual(self.live.request(method, "/api/status", host=host, body={} if method == "POST" else None).status, 403)

    def test_cross_origin_requests_are_refused(self):
        for origin in ("http://evil.com", "null", "https://127.0.0.1", f"http://127.0.0.1.evil.com:{self.live.port}", f"http://127.0.0.1:{self.live.port + 1}", "http://localhost"):
            with self.subTest(origin):
                self.assertEqual(self.live.get("/api/status", headers={"Origin": origin}).status, 403)
                self.assertEqual(self.live.post("/api/settings", {}, headers={"Origin": origin}).status, 403)
        self.assertEqual(self.live.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"}).status, 403)
        self.assertEqual(self.live.get("/api/status", headers={"Sec-Fetch-Site": "same-origin"}).status, 200)
        self.assertEqual(self.live.get("/api/status", headers={"Origin": f"http://127.0.0.1:{self.live.port}"}).status, 200)

    def test_post_needs_the_custom_header(self):
        for ctype in ("application/json", "text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
            r = self.live.post("/api/quit", {}, headers={"Content-Type": ctype}, post_header=False)
            self.assertEqual(r.status, 403, ctype)
        self.assertEqual(self.live.post("/api/settings", {}, headers={"X-ImageLoom": "0"}, post_header=False).status, 403)
        self.assertEqual(self.live.post("/api/settings", {}).status, 200)

    def test_no_cors_headers_and_no_preflight_answer(self):
        r = self.live.request("OPTIONS", "/api/generate", headers={"Origin": "http://evil.com", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-imageloom"})
        self.assertEqual(r.status, 501)
        for reply in (r, self.live.get("/api/status"), self.live.get("/api/nope"), self.live.post("/api/settings", {})):
            self.assertFalse([h for h in reply.headers if h.startswith("access-control")], reply.headers)

    def test_other_methods_are_not_implemented(self):
        for method in ("HEAD", "PUT", "DELETE", "PATCH", "TRACE"):
            self.assertEqual(self.live.request(method, "/api/status").status, 501, method)

    def test_security_headers(self):
        r = self.live.get("/api/status")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["cross-origin-resource-policy"], "same-origin")
        self.assertNotIn("python", r.headers.get("server", "").lower(), "the Python version is not advertised")
        page = self.live.get("/")
        self.assertEqual(page.status, 200)
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        self.assertIn("connect-src 'self'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["x-frame-options"], "DENY")

    def test_get_endpoints_have_no_side_effects(self):
        before = (list(server.HIST), dict(server.JOBS), list(server.QUEUE), json.dumps(server.REG.data, sort_keys=True), sorted(p.name for p in server.DATA.iterdir()))
        for path in ("/api/status", "/api/setup", "/api/models", "/api/chats", "/api/history", "/api/jobs", "/api/eta?w=512&h=512", "/", "/favicon.ico"):
            self.assertIn(self.live.get(path).status, (200, 204), path)
        after = (list(server.HIST), dict(server.JOBS), list(server.QUEUE), json.dumps(server.REG.data, sort_keys=True), sorted(p.name for p in server.DATA.iterdir()))
        self.assertEqual(before, after)


# ----------------------------------------------------------------------------------------- bodies, timeouts, connection cap
class Bodies(Case):
    def post_raw(self, headers: str, body: bytes = b"") -> bytes:
        return self.live.raw(f"POST /api/settings HTTP/1.0\r\nHost: 127.0.0.1:{self.live.port}\r\nX-ImageLoom: 1\r\n{headers}\r\n".encode() + body, timeout=3)

    def status_of(self, data: bytes) -> int:
        return int(data.split(b" ", 2)[1]) if data.startswith(b"HTTP/") else 0

    def test_content_length_must_be_a_plain_number(self):
        for cl in ("-1", "abc", "1.5", "0x10", "1e3", "+5", "١٢", "9" * 30, "-0", "1 2"):
            with self.subTest(cl):
                data = self.post_raw(f"Content-Length: {cl}\r\n", b"{}")
                self.assertIn(self.status_of(data), (400, 413), data[:80])

    def test_oversized_bodies_are_refused_before_they_are_read(self):
        data = self.post_raw(f"Content-Length: {server.MAX_JSON + 1}\r\n")
        self.assertEqual(self.status_of(data), 413)
        data = self.live.raw(f"POST /api/upload HTTP/1.0\r\nHost: 127.0.0.1:{self.live.port}\r\nX-ImageLoom: 1\r\nContent-Length: {70 * 1024 * 1024}\r\n\r\n".encode(), timeout=3)
        self.assertEqual(self.status_of(data), 413)

    def test_chunked_bodies_are_refused(self):
        data = self.post_raw("Transfer-Encoding: chunked\r\n", b"2\r\n{}\r\n0\r\n\r\n")
        self.assertEqual(self.status_of(data), 411)

    def test_json_must_be_an_object(self):
        for body in (b"[1,2]", b"5", b'"x"', b"null", b"{nope", b"\xff\xfe"):
            with self.subTest(body):
                self.assertEqual(self.live.post("/api/settings", body).status, 400)

    def test_stalled_clients_are_cut_off(self):
        with patched(server.Handler, timeout=0.5):
            t0 = time.time()
            half_line = self.live.raw(b"GET /api/sta", timeout=5)  # slowloris: never finishes the request line
            self.assertEqual(half_line, b"")
            self.assertLess(time.time() - t0, 4)
            t0 = time.time()
            short = self.live.raw(f"POST /api/upload HTTP/1.0\r\nHost: 127.0.0.1:{self.live.port}\r\nX-ImageLoom: 1\r\nContent-Length: 1000\r\n\r\nabc".encode(), timeout=5)
            # dropped on 3.10+, answered with an error status on 3.9: either way the connection is not held open
            self.assertTrue(short == b"" or short.startswith(b"HTTP/1.0 4") or short.startswith(b"HTTP/1.0 5"), short[:60])
            self.assertLess(time.time() - t0, 4)
        self.assertEqual(self.live.get("/api/status").status, 200)  # and the server is fine

    def test_timeout_is_set_in_production(self):
        self.assertGreater(server.Handler.timeout, 0)
        self.assertLessEqual(server.Handler.timeout, 60)


class ConnectionCap(unittest.TestCase):
    def test_extra_connections_are_dropped_and_slots_come_back(self):
        with patched(server, MAX_CONNECTIONS=2), LiveServer() as live:
            held = [socket.create_connection(("127.0.0.1", live.port)) for _ in range(2)]  # two clients that say nothing
            try:
                time.sleep(0.3)
                third = socket.create_connection(("127.0.0.1", live.port), timeout=3)
                try:
                    third.sendall(f"GET /api/status HTTP/1.0\r\nHost: 127.0.0.1:{live.port}\r\n\r\n".encode())
                    answer = third.recv(100)
                except ConnectionResetError:  # (closing with our request unread shows up as a reset on some systems)
                    answer = b""
                self.assertEqual(answer, b"", "the third connection is closed without an answer")
                third.close()
            finally:
                for s in held:
                    s.close()
            for _ in range(30):  # slots are released when the stalled clients leave
                try:
                    if live.get("/api/status").status == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                self.fail("the server never accepted requests again")


# ----------------------------------------------------------------------------------------- path traversal
class Traversal(Case):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        server.OUT.mkdir(parents=True, exist_ok=True)
        cls.secret_dir = S.HOME / "outside"
        cls.secret_dir.mkdir(exist_ok=True)
        cls.secret = cls.secret_dir / "secret.png"
        cls.secret.write_bytes(png_bytes(color=(1, 2, 3)))
        cls.secret_txt = cls.secret_dir / "secret.txt"
        cls.secret_txt.write_text("TOP SECRET")
        put_png("t-ok.png")
        (out("t-notes.txt")).write_text("TOP SECRET NOTES")
        (out("t-page.html")).write_text("<script>alert(1)</script>")
        cls.links = S.symlinks_work()
        if cls.links:
            for name, target in (("t-link-file.png", cls.secret), ("t-link-txt.png", cls.secret_txt), ("t-link-dir", cls.secret_dir), ("t-inner-link.png", out("t-ok.png"))):
                if not out(name).is_symlink():
                    os.symlink(str(target), str(out(name)))

    def assert_blocked(self, reply, what):
        self.assertIn(reply.status, (400, 403, 404), what)
        self.assertNotIn(b"TOP SECRET", reply.body, what)
        self.assertNotEqual(reply.body[:8], b"\x89PNG\r\n\x1a\n", what)

    def test_get_traversal_forms(self):
        attempts = [
            "../../../../etc/passwd", "..%2f..%2f..%2fetc%2fpasswd", "%2e%2e/%2e%2e/%2e%2e/etc/passwd", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "%252e%252e/%252e%252e/etc/passwd",
            "/etc/passwd", "%2Fetc%2Fpasswd", "/../../etc/passwd", "t-ok.png/../../outside/secret.png", "_uploads/../../outside/secret.png", "....//....//etc/passwd",
            "t-ok.png%00.txt", "%00", "t-ok.png%00", "..\\..\\etc\\passwd", "..%5c..%5cetc%5cpasswd", "C:\\Windows\\win.ini", "C:%5CWindows%5Cwin.ini", "C:/Windows/win.ini", "c:secret.png",
            "\\\\server\\share\\x.png", "//server/share/x.png", ".", "..", "", "t-ok.png/", "t-ok.png/.",
        ]
        for prefix in ("/img/", "/thumb/"):
            for a in attempts:
                with self.subTest(prefix + a):
                    r = self.live.get(prefix + a)
                    self.assertIn(r.status, (400, 403, 404))
                    self.assertNotIn(b"root:", r.body)
        self.assertEqual(self.live.get("/img/t-ok.png").status, 200)

    def test_only_pictures_are_served(self):
        for name in ("t-notes.txt", "t-page.html"):
            for prefix in ("/img/", "/thumb/"):
                self.assert_blocked(self.live.get(prefix + name), prefix + name)

    @unittest.skipUnless(S.symlinks_work(), "needs symlinks")
    def test_symlinks_cannot_escape_the_library(self):
        for name in ("t-link-file.png", "t-link-txt.png", "t-link-dir/secret.png", "t-link-dir/secret.txt"):
            for prefix in ("/img/", "/thumb/"):
                self.assert_blocked(self.live.get(prefix + name), prefix + name)
        self.assertEqual(self.live.get("/img/t-inner-link.png").status, 200)  # a link that stays inside is fine

    def test_every_file_taking_endpoint_refuses_escapes(self):
        bad = ["../outside/secret.png", "/etc/hosts", str(self.secret), "t-notes.txt", "t-page.html", "t-ok.png\x00.png", "..\\x.png", "C:\\x.png", "t-ok.png/../../outside/secret.png", "", ".", "..", 5, None, ["t-ok.png"], {"a": 1}]
        if self.links:
            bad += ["t-link-file.png", "t-link-dir/secret.png"]
        with patched(server, reveal=mock.Mock(), move_to_trash=mock.Mock()) as _:
            for ep, extra in (("/api/trash", {}), ("/api/reveal", {}), ("/api/export", {"format": "png"})):
                for f in bad:
                    with self.subTest(ep=ep, file=f):
                        r = self.live.post(ep, {"file": f, **extra})
                        self.assertIn(r.status, (400, 403, 404), r)
            server.reveal.assert_not_called()
            server.move_to_trash.assert_not_called()
        self.assertTrue(self.secret.exists() and self.secret_txt.exists() and out("t-notes.txt").exists())

    def test_fav_with_garbage_changes_nothing(self):
        before = json.dumps(server.HIST, sort_keys=True)
        for f in ("../outside/secret.png", 5, None, ["x"], "x\x00y"):
            self.assertEqual(self.live.post("/api/fav", {"file": f, "fav": True}).status, 200)
        self.assertEqual(json.dumps(server.HIST, sort_keys=True), before)

    def test_generate_refs_and_src_cannot_escape(self):
        with patched(server, model_ready=lambda m: True, model_can_edit=lambda m: True, any_model_ready=lambda: True, find_sd_cli=lambda: Path(__file__)):
            for refs in (["../outside/secret.png"], ["/etc/hosts"], [str(self.secret)], ["t-notes.txt"], ["t-ok.png", "../../etc/passwd"], ["t-ok.png\x00"], "t-ok.png", 5, [None]):
                with self.subTest(refs=refs):
                    r = self.live.post("/api/generate", {"mode": "edit", "prompt": "x", "width": 512, "height": 512, "refs": refs})
                    self.assertEqual(r.status, 400, r)
            with patched(server, upscale_available=lambda: {k: True for k in server.UPSCALE_MODELS}):
                for src in ("../outside/secret.png", "/etc/hosts", str(self.secret), "t-notes.txt", None, 5, ["a"]):
                    with self.subTest(src=src):
                        r = self.live.post("/api/generate", {"mode": "upscale", "src": src, "model": "quality", "target": "2x"})
                        self.assertEqual(r.status, 400, r)
        self.assertEqual(len(server.QUEUE), 0)

    def test_save_ignores_a_parent_outside_the_library(self):
        r = self.live.request("POST", "/api/save?parent=../outside/secret.png&prompt=trav", png_bytes(), headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(r.status, 200)
        row = r.json()
        self.assertIsNone(row["parent"])
        self.assertEqual(row["refs"], [])
        self.assertTrue(out(row["file"]).is_file())

    def test_safe_path_directly(self):
        self.assertEqual(server.safe_path("t-ok.png"), out("t-ok.png").resolve())
        for bad in ("../x.png", "/x.png", "a/../../x.png", "x\x00.png", "a\\b.png", "c:x.png", "", ".", "..", "t-notes.txt", "noext", None, 5, "a" * 500 + ".png", "a/./b.png", "a//b.png"):
            with self.subTest(bad), self.assertRaises(ValueError):
                server.safe_path(bad)


# ----------------------------------------------------------------------------------------- library: upload, img, thumb, export
class Library(Case):
    def upload(self, data: bytes, name: str = "pic.png"):
        return self.live.request("POST", f"/api/upload?name={name}", data, headers={"Content-Type": "application/octet-stream"})

    def test_upload_then_img_and_thumb_round_trip(self):
        png = png_bytes(8, 6, color=(200, 10, 10))
        r = self.upload(png, "my%20pic.png")
        self.assertEqual(r.status, 200, r)
        row = r.json()
        self.assertEqual((row["kind"], row["width"], row["height"], row["prompt"]), ("upload", 8, 6, "my pic.png"))
        self.assertRegex(row["file"], r"^_uploads/[0-9a-f]{20}\.png$")
        img = self.live.get("/img/" + row["file"])
        self.assertEqual((img.status, img.body, img.headers["content-type"]), (200, png, "image/png"))
        thumb = self.live.get("/thumb/" + row["file"] + "?s=256")
        self.assertEqual((thumb.status, thumb.headers["content-type"]), (200, "image/png"))  # small pictures are served as they are
        self.assertEqual(thumb.body, png)
        again = self.upload(png).json()
        self.assertEqual(again["id"], row["id"], "the same picture is stored once")
        self.assertEqual(len([h for h in server.HIST if h["file"] == row["file"]]), 1)
        listed = self.live.get("/api/history").json()
        self.assertIn(row["file"], [h["file"] for h in listed])

    @unittest.skipUnless(HAS_PIL, "needs Pillow")
    def test_big_pictures_get_a_cached_webp_thumbnail(self):
        big = png_bytes(900, 700, noise=True)
        self.assertGreater(len(big), 1_200_000)
        row = self.upload(big).json()
        before = set(server.THUMBS.iterdir())
        t = self.live.get("/thumb/" + row["file"] + "?s=300")
        self.assertEqual((t.status, t.headers["content-type"]), (200, "image/webp"))
        self.assertLess(len(t.body), len(big))
        made = set(server.THUMBS.iterdir()) - before
        self.assertEqual(len(made), 1)
        self.live.get("/thumb/" + row["file"] + "?s=310")  # sizes are rounded to 64 px steps: no new cache file for 300 vs 310
        self.assertEqual(set(server.THUMBS.iterdir()) - before, made)
        for s in range(130, 1600, 29):  # a flood of different sizes cannot create unbounded variants
            self.live.get("/thumb/" + row["file"] + f"?s={s}")
        self.assertLessEqual(len(set(server.THUMBS.iterdir()) - before), 24)
        self.assertEqual([p for p in server.THUMBS.iterdir() if ".tmp." in p.name], [], "no half-written thumbnails left")

    def test_unreadable_big_picture_falls_back_to_the_original_bytes(self):
        data = png_bytes(2, 2)[:33] + os.urandom(1_300_000)  # valid signature and header, garbage instead of pixel data: Pillow cannot decode it
        name = put_png("lib-garbage.png", data)
        t = self.live.get("/thumb/" + name)
        self.assertEqual((t.status, t.body), (200, data))
        self.assertEqual([p for p in server.THUMBS.iterdir() if ".tmp." in p.name], [])

    @unittest.skipUnless(HAS_PIL, "needs Pillow")
    def test_decompression_bombs_are_never_decoded(self):
        """A 12000x9000 PNG (108 MP) that is only ~1.5 MB on disk, dropped into the library by other means."""
        w, h = 12000, 9000
        comp, parts, row = zlib.compressobj(1), [], b"\0" * (1 + 3 * w)
        for _ in range(h):
            parts.append(comp.compress(row))
        parts.append(comp.flush())

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        bomb = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"tEXt", b"pad\0" + os.urandom(1_300_000))
                + chunk(b"IDAT", b"".join(parts)) + chunk(b"IEND", b""))
        self.assertGreater(len(bomb), 1_200_000)
        name = put_png("lib-bomb.png", bomb)
        self.assertEqual(server.Image.MAX_IMAGE_PIXELS, server.MAX_IMAGE_PIXELS)
        t0 = time.time()
        t = self.live.get("/thumb/" + name)
        self.assertEqual((t.status, t.body), (200, bomb), "the original bytes are served; no thumbnail was decoded")
        self.assertLess(time.time() - t0, 5)
        r = self.live.post("/api/export", {"file": name, "format": "png"})
        self.assertEqual(r.status, 400, r)
        self.assertFalse(server.png_has_alpha(out(name)))
        with self.assertRaises(ValueError):
            server.check_png(bomb)  # and an upload of it is refused up front (more than MAX_IMAGE_PIXELS)

    def test_upload_rejects_what_is_not_a_sane_png(self):
        good = png_bytes()
        cases = {
            "not a png": b"GIF89a" + b"x" * 60, "empty": b"", "header only": good[:20], "signature only": good[:8],
            "huge claimed size": png_bytes(dims=(60000, 60000)), "zero size": png_bytes(dims=(0, 0)), "too many pixels": png_bytes(dims=(16000, 16000)),
            "html": b"<html><script>alert(1)</script></html>", "svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>", "zip": b"PK\x03\x04" + b"\0" * 60,
        }
        if HAS_PIL:  # structural checks need Pillow
            corrupt = bytearray(good)
            corrupt[45] ^= 0xFF  # flip a byte inside the pixel data: the chunk checksum no longer matches
            cases["bad checksum"] = bytes(corrupt)
            cases["truncated"] = good[:40]
        before = len(list(server.UPLOADS.iterdir()))
        for name, data in cases.items():
            with self.subTest(name):
                r = self.upload(data)
                self.assertEqual(r.status, 400, r)
                self.assertNotIn("Traceback", r.body.decode())
        self.assertEqual(len(list(server.UPLOADS.iterdir())), before, "nothing is written for a refused upload")

    def test_upload_size_cap(self):
        r = self.live.raw(f"POST /api/upload HTTP/1.0\r\nHost: 127.0.0.1:{self.live.port}\r\nX-ImageLoom: 1\r\nContent-Length: {server.MAX_UPLOAD + 1}\r\n\r\n".encode(), timeout=3)
        self.assertIn(b" 413 ", r.split(b"\r\n")[0])

    def test_labels_are_cleaned(self):
        row = self.upload(png_bytes(3, 3, color=(9, 9, 9)), "a%0Ab%00c%1B%09d").json()
        self.assertEqual(row["prompt"], "a b c d")
        row = self.live.request("POST", "/api/save?prompt=" + "x" * 900, png_bytes(3, 3, color=(8, 8, 8)), headers={"Content-Type": "application/octet-stream"}).json()
        self.assertEqual(len(row["prompt"]), 500)
        self.assertRegex(row["file"], r"^[0-9]{8}-[0-9]{6}_composite_x+\.png$")

    def test_saved_composites_never_overwrite_each_other(self):
        a = self.live.request("POST", "/api/save?prompt=same", png_bytes(5, 5, color=(1, 1, 1)), headers={"Content-Type": "application/octet-stream"}).json()
        b = self.live.request("POST", "/api/save?prompt=same", png_bytes(5, 5, color=(2, 2, 2)), headers={"Content-Type": "application/octet-stream"}).json()
        self.assertNotEqual(a["file"], b["file"])
        self.assertNotEqual(out(a["file"]).read_bytes(), out(b["file"]).read_bytes())

    def test_history_file_stays_valid_jsonl(self):
        self.upload(png_bytes(7, 7, color=(5, 6, 7)))
        lines = server.HISTORY.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertIsInstance(json.loads(line), dict)

    def test_fav_and_trash(self):
        row = self.upload(png_bytes(9, 9, color=(3, 3, 3))).json()
        self.assertEqual(self.live.post("/api/fav", {"file": row["file"], "fav": True}).status, 200)
        stored = [json.loads(line) for line in server.HISTORY.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(next(r for r in stored if r["file"] == row["file"])["fav"])
        trashed = []
        with patched(server, move_to_trash=lambda p: (trashed.append(p), p.unlink())):
            self.assertEqual(self.live.post("/api/trash", {"file": row["file"]}).status, 200)
        self.assertEqual([p.name for p in trashed], [Path(row["file"]).name])
        self.assertNotIn(row["file"], [h["file"] for h in server.HIST])
        self.assertEqual(self.live.get("/img/" + row["file"]).status, 404)

    def test_reveal_only_for_existing_library_pictures(self):
        row = self.upload(png_bytes(9, 8, color=(4, 4, 4))).json()
        with patched(server, reveal=mock.Mock()):
            self.assertEqual(self.live.post("/api/reveal", {"file": row["file"]}).status, 200)
            server.reveal.assert_called_once_with(out(row["file"]).resolve())
            self.assertEqual(self.live.post("/api/reveal", {"file": "nope.png"}).status, 404)
            self.assertEqual(server.reveal.call_count, 1)

    @unittest.skipUnless(HAS_PIL, "needs Pillow")
    def test_export_round_trip_and_limits(self):
        row = self.upload(png_bytes(40, 30, noise=True)).json()
        r = self.live.post("/api/export", {"file": row["file"], "format": "webp", "quality": 80})
        self.assertEqual(r.status, 200, r)
        info = r.json()
        self.assertEqual((info["format"], info["width"], info["height"]), ("webp", 40, 30))
        self.assertTrue(info["file"].startswith("_exports/"))
        served = self.live.get("/img/" + info["file"])
        self.assertEqual((served.status, served.headers["content-type"]), (200, "image/webp"))
        self.assertEqual([p for p in (server.OUT / "_exports").iterdir() if p.name.endswith(".part")], [])
        small = self.live.post("/api/export", {"file": row["file"], "format": "jpeg", "quality": 9999, "max_side": 20}).json()
        self.assertEqual(small["width"], 20)
        for body in ({"format": "exe"}, {"quality": "abc"}, {"quality": [1]}, {"max_side": "x"}, {"preset": 5, "format": "svg"}):
            with self.subTest(body):
                r = self.live.post("/api/export", {"file": row["file"], **({"format": "png"} | body)})
                self.assertEqual(r.status, 400, r)


# ----------------------------------------------------------------------------------------- settings and the Hugging Face token
class Settings(Case):
    def tearDown(self):
        server.HF_TOKEN_PATH.unlink(missing_ok=True)

    def test_only_known_keys_and_types_are_accepted(self):
        for body in ({"foo": 1}, {"hf_token": 5}, {"hf_token": ["x"]}, {"hf_token": None}, {"hf_token": "hf_validtoken123", "other": 1}, {"hf_token": "has space inside"},
                     {"hf_token": "new\nline123"}, {"hf_token": "x"}, {"hf_token": "é" * 20}, {"hf_token": "a" * 600}, {"output_dir": "/tmp"}, {"port": 1}):
            with self.subTest(body):
                self.assertEqual(self.live.post("/api/settings", body).status, 400)
        self.assertFalse(server.HF_TOKEN_PATH.exists())

    def test_token_round_trip_never_leaks(self):
        tok = "hf_TESTONLYtoken0123456789"
        err, outp = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(outp):
            r = self.live.post("/api/settings", {"hf_token": f"  {tok}  "})
            self.assertEqual((r.status, r.json()), (200, {"token": True}))
            replies = [self.live.get(p) for p in ("/api/status", "/api/models", "/api/setup", "/api/chats", "/api/jobs", "/api/history")]
            replies += [self.live.post("/api/settings", {}), self.live.get("/api/doesnotexist"), self.live.post("/api/models/inspect", {"url": "https://evil.com/a/b"})]
            with patched(M, hf_json=mock.Mock(side_effect=urllib.error.URLError("unreachable"))):
                replies.append(self.live.post("/api/models/inspect", {"url": "a/b"}))
        for rep in replies:
            self.assertNotIn(tok.encode(), rep.body)
            self.assertNotIn(tok, json.dumps(rep.headers))
        self.assertNotIn(tok, err.getvalue() + outp.getvalue())
        self.assertEqual(self.live.get("/api/models").json()["token"], True)
        self.assertEqual(server.hf_token(), tok)

    @unittest.skipUnless(IS_POSIX, "POSIX permissions")
    def test_token_file_is_private_from_the_first_byte(self):
        server.HF_TOKEN_PATH.write_text("hf_oldtoken12345678")
        server.HF_TOKEN_PATH.chmod(0o644)
        self.live.post("/api/settings", {"hf_token": "hf_newtoken1234567890"})
        self.assertEqual(server.HF_TOKEN_PATH.stat().st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in server.DATA.iterdir() if p.name.startswith(".hf_token")], [], "no temp copy left")
        server.HF_TOKEN_PATH.chmod(0o644)  # and a loose file from an older version is tightened at startup
        server.tighten_token_file()
        self.assertEqual(server.HF_TOKEN_PATH.stat().st_mode & 0o777, 0o600)

    def test_empty_token_removes_it(self):
        self.live.post("/api/settings", {"hf_token": "hf_abcdefgh12345"})
        self.assertTrue(server.HF_TOKEN_PATH.exists())
        self.assertEqual(self.live.post("/api/settings", {"hf_token": "  "}).json(), {"token": False})
        self.assertFalse(server.HF_TOKEN_PATH.exists())
        self.assertIsNone(server.hf_token())

    def test_a_garbled_token_file_is_ignored_rather_than_sent(self):
        server.HF_TOKEN_PATH.write_text("hf_x\r\nX-Evil: 1")
        self.assertIsNone(server.hf_token())

    def test_downloads_send_the_token_only_to_huggingface(self):
        server.HF_TOKEN_PATH.write_text("hf_sendme1234567890")
        seen = []

        class Opener:
            def open(self, req, timeout=None):
                seen.append((req.full_url, req.get_header("Authorization")))
                raise urllib.error.URLError("stop")

        with patched(M, OPENER=Opener()):
            for url in ("https://huggingface.co/a/b/resolve/main/x.gguf", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/x.pth", "https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest"):
                with self.assertRaises(urllib.error.URLError):
                    server._http(url)
            for url in ("https://evil.com/x", "http://huggingface.co/x"):
                with self.assertRaises(ValueError):
                    server._http(url)
        self.assertEqual([a for _, a in seen], ["Bearer hf_sendme1234567890", None, None])


# ----------------------------------------------------------------------------------------- errors
class Errors(Case):
    def test_unexpected_failures_are_json_without_internals(self):
        err = io.StringIO()
        with patched(server, public_models=mock.Mock(side_effect=RuntimeError("boom at /Users/secret/path"))), contextlib.redirect_stderr(err):
            r = self.live.get("/api/models")
        self.assertEqual(r.status, 500)
        self.assertNotIn("Traceback", r.body.decode())
        self.assertNotIn("secret", r.body.decode())
        self.assertIn("boom", err.getvalue(), "the details go to the server log")
        self.assertEqual(self.live.get("/api/status").status, 200)

    def test_bad_input_is_400_not_500(self):
        for path in ("/api/eta?w=" + "9" * 400 + "&h=1", "/api/eta?w=abc&h=2", "/api/eta?h=2", "/api/eta?w=512&h=512&n=999999999999", "/api/eta?w=-5&h=512",
                     "/api/eta?mode=upscale&w=" + "9" * 50 + "&h=1&target=4k", "/api/eta?mode=upscale&w=512&h=512&model=zzz", "/api/eta?mode=upscale&w=512&h=512&target=zzz"):
            with self.subTest(path):
                r = self.live.get(path)
                self.assertEqual(r.status, 400, r)
                self.assertIn("error", r.json())
        for ep, body in (("/api/chats", {"title": ["x"], "effort": [1], "model": {"a": 1}}), ("/api/chats/zz/delete", {}), ("/api/models/add", {}), ("/api/models/delete", {"id": ["x"]}),
                         ("/api/models/active", {"id": "nope"}), ("/api/setup/start", {"ids": "engine"}), ("/api/cancel/ffff", {}), ("/api/export", {"file": "nope.png"}), ("/api/upload", None)):
            with self.subTest(ep):
                r = self.live.post(ep, body) if body is not None else self.live.request("POST", ep, b"")
                self.assertIn(r.status, (400, 404), r)
                self.assertNotIn("Traceback", r.body.decode())

    def test_hugging_face_failures_map_to_http_codes(self):
        cases = [(PermissionError("needs a token"), 403), (urllib.error.URLError("no route"), 502), (TimeoutError("slow"), 502), (ConnectionResetError("reset"), 502), (ValueError("not found"), 400)]
        for exc, code in cases:
            with self.subTest(code=code, exc=repr(exc)), patched(M, hf_json=mock.Mock(side_effect=exc)):
                r = self.live.post("/api/models/inspect", {"url": "a/b"})
                self.assertEqual(r.status, code, r)
                if code == 403:
                    self.assertTrue(r.json()["need_token"])
        with patched(server, models_add=mock.Mock(side_effect=PermissionError("gated"))):
            self.assertEqual(self.live.post("/api/models/add", {"repo": "a/b"}).status, 403)

    def test_inspect_rejects_other_hosts_without_any_request(self):
        with patched(M, hf_json=mock.Mock(side_effect=AssertionError("no network expected"))):
            for url in ("https://evil.com/a/b", "http://huggingface.co/a/b", "https://user:pw@huggingface.co/a/b", "https://huggingface.co:444/a/b", "file:///etc/passwd", "", "../x"):
                with self.subTest(url):
                    self.assertEqual(self.live.post("/api/models/inspect", {"url": url}).status, 400)


# ----------------------------------------------------------------------------------------- job validation, queue
class FakeModelReady(unittest.TestCase):
    """validate() with a ready model; nothing is enqueued unless a test does it, and spawn() is a tripwire anyway."""

    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patched(server, model_ready=lambda m: True, model_can_edit=lambda m: True, any_model_ready=lambda: True,
                                    upscale_available=lambda: {k: True for k in server.UPSCALE_MODELS}))
        put_png("v-ref.png", png_bytes(64, 48))
        with server.LOCK:
            self._saved = (dict(server.JOBS), list(server.JOB_ORDER), list(server.QUEUE))
        self.addCleanup(self.restore)

    def restore(self):
        with server.LOCK:
            server.JOBS.clear(), server.JOB_ORDER.clear(), server.QUEUE.clear()
            server.JOBS.update(self._saved[0]), server.JOB_ORDER.extend(self._saved[1]), server.QUEUE.extend(self._saved[2])

    def ok(self, **body):
        return server.validate({"prompt": "a red fox", **body})


class Validate(FakeModelReady):
    def test_defaults(self):
        spec = self.ok()
        self.assertEqual((spec["mode"], spec["width"], spec["height"], len(spec["seeds"]), spec["chat"]), ("generate", 768, 768, 1, "default"))

    def test_numbers_must_be_numbers_in_range(self):
        for body in ({"width": [1]}, {"width": "abc"}, {"width": {}}, {"width": 1e999}, {"width": 100}, {"width": 100_000_000}, {"width": 0}, {"width": -32}, {"width": 2784}, {"width": True},
                     {"width": 2752, "height": 2752}, {"height": None, "width": 31}, {"count": "abc"}, {"count": [1]}, {"count": {}}, {"seed": "abc"}, {"seed": 2**70}, {"seed": -2},
                     {"seed": [1]}, {"seed": 1.5e400}, {"effort": "x"}, {"effort": [1]}):
            with self.subTest(body), self.assertRaises(ValueError):
                self.ok(**body)

    def test_count_and_effort_are_clamped(self):
        self.assertEqual(len(self.ok(count=100)["seeds"]), 8)
        self.assertEqual(len(self.ok(count=-5)["seeds"]), 1)
        self.assertEqual(len(self.ok(count="3")["seeds"]), 3)
        self.assertEqual(self.ok(effort=99)["effort"], 3)
        self.assertEqual(self.ok(effort=-4)["effort"], 0)

    def test_seeds(self):
        self.assertEqual(self.ok(seed=5, count=3)["seeds"], [5, 6, 7])
        self.assertEqual(self.ok(seed="12")["seeds"], [12])
        self.assertEqual(self.ok(seed=0)["seeds"], [0])
        a, b = self.ok(seed=-1)["seeds"][0], self.ok(seed="")["seeds"][0]
        self.assertTrue(0 <= a < 2**24 and 0 <= b < 2**24)

    def test_prompts(self):
        for bad in (None, "", "   ", ["a"], {"a": 1}, 5, "x" * (server.MAX_PROMPT + 1), "a\x00b"):
            with self.subTest(repr(bad)[:30]), self.assertRaises(ValueError):
                server.validate({"prompt": bad})
        self.assertEqual(self.ok(prompt="x" * server.MAX_PROMPT)["prompt"], "x" * server.MAX_PROMPT)
        self.assertEqual(self.ok(prompt="  padded  ")["prompt"], "padded")

    def test_edit_references(self):
        edit = {"mode": "edit", "width": 512, "height": 512}
        self.assertEqual(self.ok(**edit, refs=["v-ref.png"])["refs"], ["v-ref.png"])
        self.assertEqual(len(self.ok(**edit, refs=["v-ref.png"] * 5)["refs"]), 3)
        for refs in ("v-ref.png", 5, None, [], ["missing.png"], ["../x.png"], [5], [None]):
            with self.subTest(refs), self.assertRaises(ValueError):
                self.ok(**edit, refs=refs)

    def test_follow_up_upscale_options(self):
        self.assertIsNone(self.ok(then="4k")["then"])
        self.assertEqual(self.ok(then={"upscale": {"model": "fast", "target": "2x"}})["then"], {"model": "fast", "target": "2x"})
        for then in ({"upscale": "4k"}, {"upscale": {"model": "nope"}}, {"upscale": {"target": "99x"}}, {"upscale": [1]}):
            with self.subTest(then), self.assertRaises(ValueError):
                self.ok(then=then)

    def test_chat_id_is_constrained(self):
        self.assertEqual(self.ok(chat="abc123")["chat"], "abc123")
        for bad in ("../x", "A B", "x" * 40, "a\x00b", "<script>", ["a"]):
            self.assertEqual(self.ok(chat=bad)["chat"], "default", bad)

    def test_upscale_mode(self):
        spec = server.validate({"mode": "upscale", "src": "v-ref.png", "model": "quality", "target": "2x"})
        self.assertEqual((spec["width"], spec["height"], spec["refs"]), (128, 96, ["v-ref.png"]))
        for body in ({"src": "missing.png"}, {"src": "../x.png"}, {"src": None}, {"src": "v-ref.png", "model": "nope"}, {"src": "v-ref.png", "target": "99k"}):
            with self.subTest(body), self.assertRaises(ValueError):
                server.validate({"mode": "upscale", "model": "quality", "target": "2x", **body})
        put_png("v-notpng.png", b"not a png at all, just text" * 5)
        with self.assertRaises(ValueError):
            server.validate({"mode": "upscale", "src": "v-notpng.png"})

    def test_prompts_cannot_inject_options_into_the_engine_command(self):
        with patched(server, sd_cli=lambda: "/engine/sd-cli"):
            for prompt in ("--help", "-p x", "--diffusion-model /etc/passwd", "-o /tmp/evil.png", "- a bullet"):
                with self.subTest(prompt):
                    spec = self.ok(prompt=prompt)
                    cmd = server.build_cmd({**spec, "id": "x"})
                    i = cmd.index("-p")
                    self.assertEqual(cmd[i + 1].strip(), prompt)
                    self.assertFalse(cmd[i + 1].startswith("-"), "a prompt value must never start with a dash")
                    self.assertEqual(cmd.count("-p"), 1)
                    self.assertEqual(cmd.count("-o"), 1)
                    self.assertNotIn("--help", cmd)
                    self.assertTrue(all(isinstance(a, str) for a in cmd))
            edit = server.build_cmd({**self.ok(mode="edit", width=512, height=512, refs=["v-ref.png"]), "id": "x"})
            r = edit[edit.index("-r") + 1]
            self.assertTrue(os.path.isabs(r) and r.endswith("v-ref.png"))

    def test_transparent_prompt_wrapping_keeps_the_prompt_intact(self):
        spec = self.ok(prompt="a logo", transparent=True)
        self.assertTrue(spec["transparent"])
        self.assertIn("a logo", spec["sd_prompt"])


class Queue(FakeModelReady):
    def setUp(self):
        super().setUp()
        with server.LOCK:
            server.JOBS.clear(), server.JOB_ORDER.clear(), server.QUEUE.clear()

    def test_the_queue_is_bounded(self):
        with patched(server, MAX_QUEUED=3):
            for i in range(3):
                server.enqueue(self.ok(prompt=f"p{i}"))
            with self.assertRaises(server.ApiError) as cm:
                server.enqueue(self.ok(prompt="one too many"))
            self.assertEqual(cm.exception.status, 429)
            self.assertEqual(len(server.QUEUE), 3)
            self.assertIn("p-front", server.enqueue(self.ok(prompt="p-front"), front=True)["prompt"])  # chained work is never starved
            self.assertEqual(server.QUEUE[0], list(server.JOBS)[-1])

    def test_finished_jobs_are_forgotten_but_active_ones_never(self):
        with patched(server, MAX_JOBS_KEPT=5):
            ids = [server.enqueue(self.ok(prompt=f"j{i}"))["id"] for i in range(4)]
            with server.LOCK:
                server.QUEUE.clear()
                for i in ids:
                    server.JOBS[i]["status"] = "done"
            more = [server.enqueue(self.ok(prompt=f"k{i}"))["id"] for i in range(6)]
            self.assertLessEqual(len(server.JOB_ORDER), 6 + 1)
            self.assertEqual(set(server.JOB_ORDER), set(server.JOBS))
            for i in more:
                self.assertIn(i, server.JOBS, "queued jobs are never dropped")

    def test_http_generate_paths(self):
        live = LiveServer().__enter__()
        self.addCleanup(live.__exit__, None, None, None)
        body = {"prompt": "a red fox"}
        with patched(server, find_sd_cli=lambda: S.NO_ENGINE):  # no engine at all
            r = live.post("/api/generate", body)
            self.assertEqual(r.status, 503, r)
            self.assertTrue(r.json()["need_engine"])
            self.assertIn("engine", r.json()["error"])
            self.assertEqual(live.post("/api/generate", {"mode": "upscale", "src": "v-ref.png"}).status, 503)
        with patched(server, find_sd_cli=lambda: Path(__file__)):  # engine present, no model
            with patched(server, any_model_ready=lambda: False):
                r = live.post("/api/generate", body)
                self.assertEqual(r.status, 503)
                self.assertIn("no model", r.json()["error"])
            r = live.post("/api/generate", {**body, "width": "wide"})
            self.assertEqual(r.status, 400, r)
            r = live.post("/api/generate", {**body, "width": 512, "height": 512})
            self.assertEqual(r.status, 202, r)
            job = r.json()
            self.assertEqual((job["status"], job["position"]), ("queued", 1))
            self.assertEqual(live.get("/api/jobs/" + job["id"]).json()["prompt"], "a red fox")
            self.assertEqual(live.post("/api/cancel/" + job["id"], {}).json()["status"], "cancelled")
            self.assertEqual(live.post("/api/cancel/" + "f" * 12, {}).status, 404)


# ----------------------------------------------------------------------------------------- state files
class StateFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="state-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hist_saved = list(server.HIST)
        self.addCleanup(lambda: server.HIST.__setitem__(slice(None), self.hist_saved))

    def test_history_with_damage_loads_the_good_rows(self):
        h = self.tmp / "history.jsonl"
        good = json.dumps({"file": "a.png", "prompt": "ok"})
        h.write_bytes("\n".join([good, "{truncated", "[1,2]", "5", json.dumps({"file": "../x.png"}), json.dumps({"file": "/abs.png"}), json.dumps({"nofile": 1}),
                                 json.dumps({"file": "sub\\w.png"}), "", json.dumps({"file": "b.png", "fav": True})]).encode() + b"\n" + b"\xff\xfe\n" + b'{"file": "half.png", "pro')
        with patched(server, HISTORY=h):
            server.load_history()
            rows = [r["file"] for r in server.HIST]
            self.assertEqual(rows, ["a.png", "sub/w.png", "b.png"])
            self.assertTrue(all(r["kind"] and r["id"] and r["refs"] == [] for r in server.HIST))
            self.assertEqual(len(list(self.tmp.glob("history.jsonl.bad-*"))), 1, "the original is kept")
            for line in h.read_text(encoding="utf-8").splitlines():  # the file itself was repaired
                json.loads(line)
            server.add_rows([{"id": "n", "file": "c.png", "alpha": False}])  # and appending after a half-written last line is clean
            self.assertEqual([json.loads(line)["file"] for line in h.read_text(encoding="utf-8").splitlines()], ["a.png", "sub/w.png", "b.png", "c.png"])

    def test_history_is_bounded(self):
        h = self.tmp / "history.jsonl"
        h.write_text("".join(json.dumps({"file": f"{i}.png"}) + "\n" for i in range(30)), encoding="utf-8")
        with patched(server, HISTORY=h, MAX_HISTORY=10):
            server.load_history()
            self.assertEqual(server.HIST[0]["file"], "20.png")
            server.add_rows([{"id": "z", "file": "z.png", "alpha": False}])
            self.assertEqual(len(server.HIST), 10)
            self.assertEqual(len(h.read_text().splitlines()), 10)

    def test_history_missing_or_unreadable_is_fine(self):
        with patched(server, HISTORY=self.tmp / "nope.jsonl"):
            server.HIST[:] = []
            server.load_history()
            self.assertEqual(server.HIST, [])

    def test_chats_damage(self):
        p = self.tmp / "chats.json"
        for content in ("{nope", "[]", '{"chats": 5}', '{"chats": ["x", 5, {"id": "../bad"}, {"id": "ok1", "title": "T"}]}', ""):
            p.write_text(content, encoding="utf-8")
            with patched(server, CHATS_PATH=p):
                data = server.load_chats()
            ids = [c["id"] for c in data["chats"]]
            self.assertEqual(ids[0], "default", content)
            self.assertTrue(set(ids) <= {"default", "ok1"}, ids)

    def test_chat_api_validates_and_is_bounded(self):
        saved = json.loads(json.dumps(server.CHATS))
        self.addCleanup(lambda: server.CHATS.update(saved))
        with patched(server, CHATS_PATH=self.tmp / "chats.json"):
            made = server.chats_api({"title": "x" * 500 + "\n\x00y", "effort": "2", "model": ["bad"]})
            c = next(c for c in made["chats"] if c["id"] == made["id"])
            self.assertEqual((len(c["title"]), c["effort"]), (60, 2))
            self.assertTrue(c["model"] is None or isinstance(c["model"], str))
            server.chats_api({"title": "t", "effort": 99, "model": "m"}, made["id"])
            c = next(c for c in server.CHATS["chats"] if c["id"] == made["id"])
            self.assertEqual((c["title"], c["effort"], c["model"]), ("t", 9, "m"))
            with self.assertRaises(ValueError):
                server.chats_api({"effort": [1]}, made["id"])
            with self.assertRaises(ValueError):
                server.chats_api({}, "default", delete=True)
            with patched(server, MAX_CHATS=len(server.CHATS["chats"])):
                server.chats_api({}, made["id"], delete=True)  # archived chats are dropped to make room for a new one
                self.assertIsNotNone(server.chats_api({"title": "again"})["id"])
                with self.assertRaises(ValueError):
                    server.chats_api({"title": "over the limit"})
            json.loads((self.tmp / "chats.json").read_text(encoding="utf-8"))

    def test_config_json_damage_and_allow_list(self):
        p = self.tmp / "config.json"
        with patched(server, CONFIG_PATH=p):
            p.write_text("{nope", encoding="utf-8")
            self.assertEqual(server.load_config(), server.DEFAULTS)
            self.assertTrue(list(self.tmp.glob("config.json.bad-*")))
            p.write_text(json.dumps({"port": 7999, "steps": "many", "unknown": 1, "output_dir": "/x", "extra_args": ["--a", 5], "min_side": 640.0, "warn_pixels": True}), encoding="utf-8")
            cfg = server.load_config()
        self.assertEqual((cfg["port"], cfg["output_dir"], cfg["min_side"]), (7999, "/x", 640.0))
        self.assertEqual(cfg["steps"], server.DEFAULTS["steps"])  # wrong type ignored
        self.assertEqual(cfg["extra_args"], server.DEFAULTS["extra_args"])  # a list with a non-string is not accepted
        self.assertEqual(cfg["warn_pixels"], server.DEFAULTS["warn_pixels"])  # bool is not a number here
        self.assertNotIn("unknown", cfg)
        self.assertTrue(any("unknown" in w for w in S.WARNINGS))

    def test_stats_damage(self):
        p = self.tmp / "eta_stats.json"
        with patched(server, STATS_PATH=p):
            p.write_text("[1,2]", encoding="utf-8")
            self.assertEqual(server._load_stats(), {})
            p.write_text("{oops", encoding="utf-8")
            self.assertEqual(server._load_stats(), {})
            old = dict(server.STATS)
            self.addCleanup(lambda: (server.STATS.clear(), server.STATS.update(old)))
            server.record_stat("m", "gen", 262144, 100.0)
            self.assertEqual(json.loads(p.read_text())["m"]["gen"], [[262144, 100.0]])

    def test_startup_notes_are_plain_words(self):
        with patched(server, find_sd_cli=lambda: S.NO_ENGINE, any_model_ready=lambda: False):
            notes = server.startup_notes()
        self.assertTrue(any("engine" in n and "IMAGELOOM_SD_CLI" in n for n in notes), notes)
        self.assertTrue(any("models" in n for n in notes), notes)


# ----------------------------------------------------------------------------------------- the registry in the server
class ServerRegistry(unittest.TestCase):
    def test_the_server_registry_is_rooted_at_the_data_folder(self):
        self.assertEqual(server.REG.base, Path(os.path.abspath(server.DATA)))

    def test_migration_through_the_server_objects(self):
        d = Path(tempfile.mkdtemp(prefix="migr-")).resolve()
        self.addCleanup(shutil.rmtree, d, True)
        f = d / "models" / "x" / "w.safetensors"
        (d / "models.json").write_text(json.dumps({"models": [{"id": "x", "name": "X", "family": "sdxl", "files": {"checkpoint": str(f)}, "status": "ready"}], "active": "x"}), encoding="utf-8")
        reg = M.Registry(d / "models.json", server.builtin_model(), d)
        self.assertEqual(json.loads((d / "models.json").read_text())["models"][0]["files"], {"checkpoint": "models/x/w.safetensors"})
        self.assertEqual(reg.get(None)["id"], "x")
        self.assertEqual(M.sd_args(reg.get("x"), "generate")[:2], ["-m", str(f)])


# ----------------------------------------------------------------------------------------- engine download
def make_zip(path: Path, entries: dict) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


class EngineInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.eng = self.tmp / "data" / "engine"
        self.eng.mkdir(parents=True)

    def tree(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*"))

    def test_zip_slip_archives_are_refused_whole(self):
        for bad in ("../evil", "../../evil2", "/abs/evil3", "..\\win-evil", "a/b/../../c", "C:\\x.dll", "c:/x.dll", "ok/../../up"):
            with self.subTest(bad):
                z = make_zip(self.tmp / "e.zip", {"sd-cli": b"#!bin", "libstable-diffusion.dylib": b"lib", bad: b"owned"})
                with self.assertRaisesRegex(RuntimeError, "unsafe path"):
                    server.install_engine_zip(z, self.eng)
                self.assertEqual(list(self.eng.iterdir()), [], "nothing is installed from a tampered archive")
                self.assertFalse([n for n in self.tree() if "evil" in n or n.endswith(("x.dll", "/up", "/c"))], self.tree())
        self.assertFalse(Path("/abs/evil3").exists())

    def test_plain_archives_install_flat_names_only(self):
        z = make_zip(self.tmp / "e.zip", {
            "sd-cli": b"#!bin", "sd-server": b"x", "libstable-diffusion.dylib": b"lib", "ggml.txt": b"license", "README.md": b"x",
            "nested/dir/ggml.dll": b"dll", "-flag": b"x", ".hidden": b"x", "name with space": b"x", "dir/": b"", "con": b"x", "CON.dll": b"x",
        })
        server.install_engine_zip(z, self.eng)
        # directories are flattened away; text files, hidden or odd names and Windows device names are skipped
        self.assertEqual(sorted(p.name for p in self.eng.iterdir()), ["ggml.dll", "libstable-diffusion.dylib", "sd-cli", "sd-server"])
        self.assertFalse((self.eng / ".unpack").exists(), "the staging folder is removed")
        self.assertEqual((self.eng / "sd-cli").read_bytes(), b"#!bin")
        if IS_POSIX:
            self.assertTrue(os.access(self.eng / "sd-cli", os.X_OK))

    def test_an_archive_without_sd_cli_installs_nothing(self):
        (self.eng / "sd-cli").write_bytes(b"old")
        z = make_zip(self.tmp / "e.zip", {"libx.dylib": b"x", "other": b"y"})
        with self.assertRaises(RuntimeError):
            server.install_engine_zip(z, self.eng)
        self.assertEqual(sorted(p.name for p in self.eng.iterdir()), ["sd-cli"])
        self.assertEqual((self.eng / "sd-cli").read_bytes(), b"old")

    def test_bounds_on_entries_and_unpacked_size(self):
        many = make_zip(self.tmp / "many.zip", {f"f{i}": b"x" for i in range(10)} | {"sd-cli": b"x"})
        with patched(server, MAX_ENGINE_ENTRIES=5), self.assertRaises(RuntimeError):
            server.install_engine_zip(many, self.eng)
        big = make_zip(self.tmp / "big.zip", {"sd-cli": b"x", "huge": b"\0" * 50_000})
        with patched(server, MAX_ENGINE_UNPACKED=10_000), self.assertRaises(RuntimeError):
            server.install_engine_zip(big, self.eng)
        self.assertEqual(list(self.eng.iterdir()), [], "a refused archive leaves nothing behind")

    def test_a_corrupt_archive_fails_cleanly(self):
        bad = self.tmp / "bad.zip"
        bad.write_bytes(b"PK\x03\x04 this is not really a zip")
        with self.assertRaisesRegex(RuntimeError, "damaged"):
            server.install_engine_zip(bad, self.eng)
        self.assertEqual(list(self.eng.iterdir()), [])

    # --- the whole download_engine flow with the network stubbed
    def release(self, zip_bytes: bytes, **over):
        name = {"Darwin": "sd-master-abc-bin-Darwin-macOS-26-arm64.zip", "Windows": "sd-master-abc-bin-win-vulkan-x64.zip"}.get(server.SYSTEM, "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip")
        asset = {"name": name, "size": len(zip_bytes), "digest": "sha256:" + hashlib.sha256(zip_bytes).hexdigest(),
                 "browser_download_url": "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-abc/" + name, **over}
        return {"assets": [{"name": "other.zip", "size": 1, "browser_download_url": "https://github.com/x"}, asset]}

    def run_flow(self, rel: dict, zip_bytes: bytes):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_download(url, dest, expected, st):
            self.last_download = (url, expected)
            Path(dest).write_bytes(zip_bytes)

        with patched(server, DATA=self.tmp / "data", engine_supported=lambda: True, _http=lambda url, headers=None: Resp(json.dumps(rel).encode()), download_file=fake_download):
            server.download_engine({})

    def test_download_engine_verifies_sha256_and_installs(self):
        data = make_zip(self.tmp / "src.zip", {"sd-cli": b"BIN", "libx.dylib": b"x"}).read_bytes()
        self.run_flow(self.release(data), data)
        self.assertEqual((self.eng / "sd-cli").read_bytes(), b"BIN")
        self.assertFalse((self.eng / "_engine.zip").exists())
        self.assertTrue(self.last_download[0].startswith("https://github.com/leejet/stable-diffusion.cpp/releases/download/"))

    def test_download_engine_rejects_a_wrong_checksum(self):
        data = make_zip(self.tmp / "src.zip", {"sd-cli": b"BIN"}).read_bytes()
        with self.assertRaisesRegex(RuntimeError, "sha256"):
            self.run_flow(self.release(data, digest="sha256:" + "0" * 64), data)
        self.assertEqual(list(self.eng.iterdir()), [], "neither the archive nor any file is kept")

    def test_download_engine_without_a_digest_still_installs(self):
        data = make_zip(self.tmp / "src.zip", {"sd-cli": b"BIN"}).read_bytes()
        self.run_flow(self.release(data, digest=None), data)
        self.assertTrue((self.eng / "sd-cli").exists())

    def test_download_engine_rejects_odd_release_metadata(self):
        data = make_zip(self.tmp / "src.zip", {"sd-cli": b"BIN"}).read_bytes()
        for over in ({"browser_download_url": "https://evil.com/leejet/stable-diffusion.cpp/releases/download/x.zip"}, {"browser_download_url": "http://github.com/leejet/stable-diffusion.cpp/releases/download/x.zip"},
                     {"browser_download_url": "https://github.com/other/repo/releases/download/x.zip"}, {"browser_download_url": None}, {"size": server.MAX_ENGINE_ZIP + 1}, {"size": 0}, {"size": "9"}):
            with self.subTest(over), self.assertRaises(RuntimeError):
                self.run_flow(self.release(data, **over), data)
        with self.assertRaises(RuntimeError):
            self.run_flow({"assets": []}, data)
        self.assertEqual(list(self.eng.iterdir()), [])

    def test_unsupported_platform_gives_a_plain_message(self):
        with patched(server, engine_supported=lambda: False), self.assertRaisesRegex(RuntimeError, "IMAGELOOM_SD_CLI"):
            server.download_engine({})


# ----------------------------------------------------------------------------------------- file downloads
class FileHandler(BaseHTTPRequestHandler):
    payload = b""
    mode = "normal"
    seen: ClassVar[list] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        type(self).seen.append(dict(self.headers.items()))
        data, start = type(self).payload, 0
        rng = self.headers.get("Range")
        if rng and type(self).mode != "ignore-range":
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(data):
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body) if type(self).mode != "short" else len(body) + 100))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:  # the client hung up on purpose
            pass


class Downloads(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dl-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.handler = type("H", (FileHandler,), {"payload": os.urandom(300_000), "mode": "normal", "seen": []})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/f"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patched(server, _http=lambda url, headers=None: opener.open(urllib.request.Request(url, headers=headers or {}), timeout=5), SETUP={"running": False, "cancel": False, "items": {}}))
        self.sleeps = []
        stack.enter_context(patched(time, sleep=self.sleeps.append))

    def test_complete_download_is_renamed_only_at_the_end(self):
        dest = self.tmp / "m" / "file.bin"
        st = {}
        server.download_file(self.url, dest, len(self.handler.payload), st)
        self.assertEqual(dest.read_bytes(), self.handler.payload)
        self.assertFalse(dest.with_name("file.bin.part").exists())
        self.assertEqual(st["bytes"], len(self.handler.payload))

    def test_resume_continues_the_part_file(self):
        dest = self.tmp / "file.bin"
        part = dest.with_name("file.bin.part")
        part.write_bytes(self.handler.payload[:100_000])
        server.download_file(self.url, dest, len(self.handler.payload), {})
        self.assertEqual(dest.read_bytes(), self.handler.payload)
        self.assertEqual(self.handler.seen[0]["Range"], "bytes=100000-")

    def test_a_server_that_ignores_range_restarts_cleanly(self):
        self.handler.mode = "ignore-range"
        dest = self.tmp / "file.bin"
        dest.with_name("file.bin.part").write_bytes(b"junk" * 1000)
        server.download_file(self.url, dest, len(self.handler.payload), {})
        self.assertEqual(dest.read_bytes(), self.handler.payload)

    def test_truncated_transfers_never_become_the_final_file(self):
        self.handler.mode = "short"  # announces more bytes than it sends, then closes
        dest = self.tmp / "file.bin"
        with self.assertRaises(RuntimeError):
            server.download_file(self.url, dest, len(self.handler.payload), {})
        self.assertFalse(dest.exists())

    def test_much_more_data_than_expected_is_cut_off(self):
        self.handler.payload = os.urandom(3_000_000)
        dest = self.tmp / "file.bin"
        with patched(server, MAX_FILE_BYTES=2_000_000), self.assertRaisesRegex(RuntimeError, "more|far more"):
            server.download_file(self.url, dest, 0, {})
        self.assertFalse(dest.exists())

    def test_size_check_before_rename(self):
        dest = self.tmp / "file.bin"
        with self.assertRaisesRegex(RuntimeError, "smaller than expected"):
            server.download_file(self.url, dest, len(self.handler.payload) * 2, {})
        self.assertFalse(dest.exists())

    def test_http_errors_and_refused_redirects_are_not_retried_forever(self):
        def failing(code):
            def raiser(url, headers=None):
                err = urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
                self.addCleanup(err.close)
                raise err
            return raiser
        for code in (401, 403, 404, 302, 307):
            self.sleeps.clear()
            with self.subTest(code), patched(server, _http=failing(code)), self.assertRaisesRegex(RuntimeError, str(code)):
                server.download_file(self.url, self.tmp / f"f{code}", 10, {})
            self.assertEqual(self.sleeps, [], "fatal errors do not wait and retry")
        self.sleeps.clear()
        with patched(server, _http=failing(503)), self.assertRaises(RuntimeError):
            server.download_file(self.url, self.tmp / "f503", 10, {})
        self.assertEqual(len(self.sleeps), 6)  # transient errors are retried a few times, then reported

    def test_a_full_disk_stops_at_once(self):
        import errno

        def full(url, headers=None):
            raise OSError(errno.ENOSPC, "No space left on device")
        with patched(server, _http=full), self.assertRaisesRegex(RuntimeError, "disk is full"):
            server.download_file(self.url, self.tmp / "f", 10, {})
        self.assertEqual(self.sleeps, [])

    def test_dropped_connections_are_resumed(self):
        calls = []
        real = server._http

        def flaky(url, headers=None):
            calls.append(headers)
            if len(calls) == 1:
                raise http.client.IncompleteRead(b"abc", 100)
            return real(url, headers)
        with patched(server, _http=flaky):
            server.download_file(self.url, self.tmp / "f", len(self.handler.payload), {})
        self.assertEqual((self.tmp / "f").read_bytes(), self.handler.payload)
        self.assertEqual(len(calls), 2)

    def test_cancel(self):
        server.SETUP["cancel"] = True
        with self.assertRaises(server.Cancelled):
            server.download_file(self.url, self.tmp / "f", len(self.handler.payload), {})
        self.assertFalse((self.tmp / "f").exists())


# ----------------------------------------------------------------------------------------- adding models (and the engine)
class ModelsAdd(unittest.TestCase):
    ROUTES: ClassVar[dict] = {"someone/Qwen-Image-2.1-Turbo-GGUF/tree": "qwen21_tree.json", "someone/Qwen-Image-2.1-Turbo-GGUF": "qwen21_info.json",
              "Qwen/Qwen3-VL-8B-Instruct-GGUF/tree": "qwen3vl_tree.json", "Comfy-Org/Qwen-Image-2.1/tree": "comfy_qwen21_tree.json",
              "evil/model-GGUF/tree": "hostile_tree.json", "evil/model-GGUF": "hostile_info.json"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="add-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = self.tmp / "data"
        self.data.mkdir()
        self.engine = self.data / "engine" / "sd-cli"
        self.calls: list = []
        self.gate = threading.Event()
        self.gate.set()
        self.engine_error = None
        self.trashed: list = []
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.reg = M.Registry(self.data / "models.json", server.builtin_model(), self.data)
        stack.enter_context(patched(shutil, disk_usage=lambda p: mock.Mock(free=10**13, total=10**13, used=0)))
        stack.enter_context(patched(server, DATA=self.data, REG=self.reg, SETUP={"running": False, "cancel": False, "items": {}}, find_sd_cli=lambda: self.engine,
                                    engine_supported=lambda: True, download_file=self.fake_file, download_engine=self.fake_engine, move_to_trash=lambda p: (self.trashed.append(p), p.unlink())))
        stack.enter_context(patched(M, hf_json=S.fake_hf(self.ROUTES)))
        self.addCleanup(self.wait_idle)

    def fake_file(self, url, dest, expected, st):
        self.gate.wait(5)
        self.calls.append(("file", Path(dest).name))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.truncate(2_000_000)  # the registry only needs files that look big enough
        st.update(bytes=expected, total=expected)

    def fake_engine(self, st):
        self.gate.wait(5)
        self.calls.append(("engine", None))
        if self.engine_error:
            raise RuntimeError(self.engine_error)
        self.engine.parent.mkdir(parents=True, exist_ok=True)
        self.engine.write_bytes(b"fake engine, never executed")

    def wait_idle(self, timeout=10):
        self.gate.set()
        end = time.time() + timeout
        while server.SETUP["running"] and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(server.SETUP["running"], "the download thread did not finish")

    URL = "https://huggingface.co/someone/Qwen-Image-2.1-Turbo-GGUF"
    BODY: ClassVar[dict] = {"repo": "someone/Qwen-Image-2.1-Turbo-GGUF", "family": "qwen-image-2.1", "variant": "turbo", "file": "Qwen-Image-2.1-Turbo-Q8_0.gguf", "name": "My Qwen"}

    def stored(self):
        return json.loads((self.data / "models.json").read_text(encoding="utf-8"))["models"][0]

    def test_clean_install_fetches_the_engine_first_and_is_ready_only_after_both(self):
        self.gate.clear()  # hold the first download so the in-between state is observable
        out_ = server.models_add(dict(self.BODY))
        mid = next(m["id"] for m in out_["models"] if not m["builtin"])
        m = next(m for m in out_["models"] if m["id"] == mid)
        self.assertEqual((m["status"], m["ready"]), ("downloading", False))
        self.assertIn(f"m:{mid}:engine", m["downloading"], "the engine is part of this model's progress")
        self.assertEqual(next(iter(server.SETUP["items"])), f"m:{mid}:engine", "the engine is queued before the model files")
        self.gate.set()
        self.wait_idle()
        kinds = [c[0] for c in self.calls]
        self.assertEqual(kinds[0], "engine", self.calls)
        self.assertEqual(kinds.count("engine"), 1)
        self.assertEqual(sorted(n for k, n in self.calls if k == "file"), sorted(["Qwen-Image-2.1-Turbo-Q8_0.gguf", "Qwen3VL-8B-Instruct-Q8_0.gguf", "qwen_image_2.1_vae_bf16.safetensors", "mmproj-Qwen3VL-8B-Instruct-F16.gguf"]))
        self.assertEqual(self.reg.get(mid)["status"], "ready")
        self.assertTrue(server.model_ready(self.reg.get(mid)))
        self.assertTrue(self.engine.is_file())

    def test_http_route_on_a_clean_install(self):
        """POST /api/models/add over HTTP into an empty data folder (no engine): a 503 for jobs until the engine arrived, ready only at the end."""
        with LiveServer() as live:
            self.assertFalse(live.get("/api/status").json()["engine_found"])
            self.gate.clear()
            r = live.post("/api/models/add", self.BODY)
            self.assertEqual(r.status, 200, r)
            mid = next(m["id"] for m in r.json()["models"] if not m["builtin"])
            mid_state = next(m for m in live.get("/api/models").json()["models"] if m["id"] == mid)
            self.assertEqual((mid_state["status"], mid_state["ready"], mid_state["can_edit"]), ("downloading", False, False))
            self.assertEqual(sorted(mid_state["downloading"]).count(f"m:{mid}:engine"), 1)
            gen = live.post("/api/generate", {"prompt": "a red fox", "model": mid})
            self.assertEqual(gen.status, 503, gen)
            self.assertTrue(gen.json()["need_engine"])
            self.assertIn("engine", gen.json()["error"])
            self.assertEqual(live.post("/api/models/add", {**self.BODY, "name": "Other"}).status, 400, "one batch at a time")
            self.gate.set()
            self.wait_idle()
            final = next(m for m in live.get("/api/models").json()["models"] if m["id"] == mid)
            self.assertEqual((final["status"], final["ready"], final["can_edit"]), ("ready", True, True))
            self.assertTrue(live.get("/api/status").json()["engine_found"])
            self.assertEqual({k: v["state"] for k, v in final["downloading"].items()}[f"m:{mid}:engine"], "done")

    def test_a_failed_engine_download_never_leaves_a_ready_model(self):
        self.engine_error = "no route to github.com"
        server.models_add(dict(self.BODY))
        self.wait_idle()
        mid = self.stored()["id"]
        self.assertEqual(self.reg.get(mid)["status"], "error")
        self.assertFalse(server.model_ready(self.reg.get(mid)))
        item = server.SETUP["items"][f"m:{mid}:engine"]
        self.assertEqual((item["state"], item["error"]), ("error", "no route to github.com"))

    def test_the_model_is_not_ready_when_the_engine_is_still_missing_at_the_end(self):
        with patched(server, download_engine=lambda st: self.calls.append(("engine", None))):  # "succeeds" but installs nothing
            server.models_add(dict(self.BODY))
            self.wait_idle()
        self.assertEqual(self.reg.get(self.stored()["id"])["status"], "error")

    def test_with_the_engine_present_only_the_model_files_are_fetched(self):
        self.engine.parent.mkdir(parents=True)
        self.engine.write_bytes(b"x")
        out_ = server.models_add(dict(self.BODY))
        self.wait_idle()
        self.assertEqual([k for k, _ in self.calls].count("engine"), 0)
        self.assertFalse([k for k in server.SETUP["items"] if k.endswith(":engine")])
        self.assertEqual(self.reg.get(next(m["id"] for m in out_["models"] if not m["builtin"]))["status"], "ready")

    def test_no_prebuilt_engine_is_reported_before_anything_is_registered(self):
        with patched(server, engine_supported=lambda: False), self.assertRaisesRegex(ValueError, "IMAGELOOM_SD_CLI"):
            server.models_add(dict(self.BODY))
        self.assertEqual(self.reg.data["models"], [])
        self.assertFalse(server.SETUP["running"])

    def test_registry_paths_are_relative_and_inside_the_models_folder(self):
        server.models_add(dict(self.BODY))
        self.wait_idle()
        files = self.stored()["files"]
        mid = self.stored()["id"]
        self.assertEqual(files["diffusion"], f"models/{mid}/Qwen-Image-2.1-Turbo-Q8_0.gguf")
        for role in ("llm", "vae", "llm_vision"):
            self.assertTrue(files[role].startswith("models/_shared/"), files)
        for p in files.values():
            self.assertFalse(os.path.isabs(p))
            self.assertNotIn("..", p.split("/"))

    def test_only_one_download_batch_at_a_time(self):
        self.gate.clear()
        server.models_add(dict(self.BODY))
        with self.assertRaisesRegex(ValueError, "download"):
            server.models_add({**self.BODY, "name": "Second"})
        with self.assertRaisesRegex(ValueError, "download"):
            server.setup_start(["engine"])
        racers, errors = [], []

        def go():
            try:
                server.start_downloads([{"id": "x", "size": 1, "url": "u", "path": str(self.tmp / "x")}])
                racers.append(1)
            except ValueError as exc:
                errors.append(exc)
        self.gate.set()
        self.wait_idle()
        threads = [threading.Thread(target=go) for _ in range(8)]
        with patched(server, download_file=lambda *a: time.sleep(0.6)):
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.wait_idle()
        self.assertEqual((len(racers), len(errors)), (1, 7), "the download slot is claimed atomically")

    def test_choices_must_come_from_the_repository_listing(self):
        for file in ("../../etc/passwd", "/etc/passwd", "Qwen-Image-2.1-Turbo-lora.safetensors", "README.md", None, 5, ["x"], "Nope.gguf"):
            with self.subTest(file), self.assertRaisesRegex(ValueError, "choose one"):
                server.models_add({**self.BODY, "file": file})
        for body in ({"family": "nope"}, {"repo": "http://evil.com/a/b"}, {"repo": ""}, {}, {"repo": ["x"]}):
            with self.subTest(body), self.assertRaises(ValueError):
                server.models_add({**self.BODY, **body} if body else {})
        self.assertEqual(self.reg.data["models"], [])
        self.assertEqual(self.calls, [])

    def test_hostile_listing_names_never_reach_the_disk(self):
        body = {"repo": "evil/model-GGUF", "family": "custom", "file": "good-model-Q4_0.gguf"}
        server.models_add(body)
        self.wait_idle()
        for bad in ("../../evil-Q4_0.gguf", "/etc/cron.d/evil-Q4_0.gguf"):
            with self.assertRaisesRegex(ValueError, "choose one"):
                server.models_add({**body, "file": bad})
        written = [p for p in self.tmp.rglob("*") if p.is_file() and p.suffix == ".gguf"]
        self.assertEqual([p.name for p in written], ["good-model-Q4_0.gguf"])
        self.assertTrue(all((self.data / "models").resolve() in p.resolve().parents for p in written))

    def test_odd_but_listed_names_are_sanitised(self):
        tree = [{"type": "file", "path": "we ird&dir/na me;rm -rf-Q4_0.gguf", "size": 2_000_000_000, "lfs": {"size": 2_000_000_000}}]
        with patched(M, hf_json=lambda path, token=None, timeout=40: tree if "/tree/" in path else {"tags": ["gguf"]}):
            server.models_add({"repo": "odd/odd-GGUF", "family": "custom", "file": "we ird&dir/na me;rm -rf-Q4_0.gguf", "name": "x\x00y\n" + "n" * 200})
        self.wait_idle()
        st = self.stored()
        name = Path(st["files"]["diffusion"]).name
        self.assertRegex(name, r"^[A-Za-z0-9._-]+\.gguf$")
        self.assertNotIn(" ", name)
        self.assertEqual(len(st["name"]), 80)
        self.assertNotIn("\x00", st["name"])
        self.assertRegex(st["id"], r"^[a-z0-9-]+$")

    def test_size_sanity(self):
        for size in (0, 10, server.MAX_FILE_BYTES + 1):
            tree = [{"type": "file", "path": f"m-{size}-Q4_0.gguf", "size": size, "lfs": {"size": size}}]
            with patched(M, hf_json=lambda path, token=None, timeout=40, t=tree: t if "/tree/" in path else {"tags": []}):
                with self.subTest(size), self.assertRaisesRegex(ValueError, "weights"):
                    server.models_add({"repo": "a/b", "family": "custom", "file": f"m-{size}-Q4_0.gguf"})

    def test_not_enough_disk_space_is_reported(self):
        usage = mock.Mock(free=1_000_000, total=10**12, used=10**12)
        with patched(shutil, disk_usage=lambda p: usage), self.assertRaisesRegex(ValueError, "not enough disk space"):
            server.models_add(dict(self.BODY))
        self.assertEqual(self.reg.data["models"], [])

    def test_the_built_in_id_and_reserved_folders_are_off_limits(self):
        with self.assertRaisesRegex(ValueError, "built-in"):
            with patched(M, slug=lambda t: server.MODELS.name):
                server.models_add(dict(self.BODY))

    # --- deleting
    def test_delete_only_touches_files_inside_the_models_folder_and_not_shared_ones(self):
        root = self.data / "models"
        mine = root / "m1" / "w.safetensors"
        shared = root / "_shared" / "ae.safetensors"
        keep_other = root / "_shared" / "used-by-other.safetensors"
        outside = self.tmp / "users-own-file.safetensors"
        for p in (mine, shared, keep_other, outside):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * 10)
        mine.with_name("w.safetensors.part").write_bytes(b"partial")
        self.reg.add({"id": "m1", "name": "m1", "family": "sdxl", "files": {"checkpoint": str(mine), "vae": str(shared), "x": str(keep_other), "o": str(outside), "evil": "/etc/hosts"}, "status": "ready"})
        self.reg.add({"id": "m2", "name": "m2", "family": "sdxl", "files": {"checkpoint": str(root / "m2" / "q.safetensors"), "vae": str(keep_other)}, "status": "ready"})
        server.models_delete("m1")
        self.assertEqual(sorted(p.name for p in self.trashed), ["ae.safetensors", "w.safetensors"])
        self.assertTrue(outside.exists(), "files outside the models folder are never deleted")
        self.assertTrue(keep_other.exists(), "files another model still uses stay")
        self.assertFalse(mine.with_name("w.safetensors.part").exists())
        self.assertTrue(Path("/etc/hosts").exists())
        self.assertIsNone(self.reg.get("m1"))
        self.assertFalse((root / "m1").exists(), "the emptied model folder is removed")

    def test_delete_refuses_unknown_and_built_in_models(self):
        for mid in ("../../x", "", "qwen21-turbo-q8", "nope"):
            with self.subTest(mid), self.assertRaises(ValueError):
                server.models_delete(mid)

    def test_builtin_files_are_never_deleted_even_if_a_registry_entry_points_at_them(self):
        bf = Path(self.reg.builtin["files"]["diffusion"])
        bf.parent.mkdir(parents=True, exist_ok=True)
        bf.write_bytes(b"x")
        self.addCleanup(lambda: bf.unlink(missing_ok=True))
        with patched(server, DATA=S.DATA):  # the built-in model lives under the (test) data folder's models/
            self.reg.add({"id": "twin", "name": "twin", "family": "sdxl", "files": {"checkpoint": str(bf)}, "status": "ready"})
            server.models_delete("twin")
        self.assertEqual(self.trashed, [])
        self.assertTrue(bf.exists())


if __name__ == "__main__":
    unittest.main()
