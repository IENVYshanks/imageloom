"""ImageLoom: Windows host. Run as `python\\pythonw.exe app\\app.py` (plain Python files, no freezing).

Starts core\\server.py as a subprocess of the same interpreter, waits until it answers, then shows the UI in a
pywebview window (WebView2). If pywebview or the WebView2 runtime is unusable it falls back to `msedge --app=` (or the
default browser). Closing the window stops the server this host started; a second launch only opens another window.
"""
from __future__ import annotations

import html
import json
import locale
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

NAME = "ImageLoom"
ROOT = Path(__file__).resolve().parent  # <install>\app
SERVER_PY = ROOT / "core" / "server.py"
ENGINE = ROOT.parent / "engine"
ICON = ROOT / "app.ico"
IS_WIN = os.name == "nt"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEVNULL = subprocess.DEVNULL
LOG = None


def ui_lang() -> str:
    """'ru' when the Windows UI language (or, elsewhere, the locale) is Russian, otherwise 'en'."""
    if IS_WIN:
        try:
            import ctypes
            return "ru" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x19 else "en"  # 0x19 = LANG_RUSSIAN
        except Exception:  # noqa: BLE001
            pass
    try:
        name = (locale.getlocale()[0] or os.environ.get("LANG", "")).lower()
    except Exception:  # noqa: BLE001
        name = ""
    return "ru" if name.startswith(("ru", "russian")) else "en"


LANG = ui_lang()
STR = {  # the few texts this host shows itself; the web UI has its own language switch and detection
    "starting": {"en": "Starting {name}…", "ru": "Запуск {name}…"},
    "server_failed_title": {"en": "Couldn't start the server", "ru": "Не удалось запустить сервер"},
    "log_label": {"en": "Log", "ru": "Журнал"},
    "busy_title": {"en": "Generation in progress", "ru": "Идёт генерация"},
    "busy_text": {"en": "If you close the window now, the current job and the queue ({queued}) will be cancelled. Close it?",
                  "ru": "Если закрыть окно сейчас, текущая задача и очередь ({queued}) будут отменены. Закрыть?"},
    "server_failed": {"en": "The server did not start. Details are in the log:\n{log}", "ru": "Сервер не запустился. Подробности в журнале:\n{log}"},
    "startup_error": {"en": "Startup error:\n", "ru": "Ошибка запуска:\n"},
}


def tr(key: str, **kw) -> str:
    return STR[key][LANG].format(**kw)


PAGE = ('<html lang="' + LANG + '"><body style="margin:0;height:100vh;display:grid;place-items:center;background:#111110;color:#ecece7;'
        'font:15px Segoe UI,system-ui,sans-serif"><div style="max-width:720px;padding:24px">@@</div>'
        '<style>@keyframes s{to{transform:rotate(360deg)}}</style></body></html>')
SPINNER = ('<div style="text-align:center"><div style="width:34px;height:34px;border:3px solid #333;border-top-color:#7a89ff;'
           'border-radius:50%;margin:0 auto 16px;animation:s 1s linear infinite"></div>' + html.escape(tr("starting", name=NAME)) + '</div>')


def data_dir() -> Path:
    """Same rule as default_data_dir() in core/server.py (server.json and the logs live there)."""
    if os.environ.get("IMAGELOOM_HOME"):
        return Path(os.environ["IMAGELOOM_HOME"]).expanduser()
    legacy = Path.home() / ".local" / "share" / "imageloom"
    if (legacy / "models" / "qwen21-turbo-q8-uncensored").is_dir():
        return legacy
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / NAME


DATA = data_dir()


def open_log() -> None:
    """One log file for the server's output and this host's own lines (%LOCALAPPDATA%\\ImageLoom\\logs\\server.log)."""
    global LOG
    try:
        d = DATA / "logs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "server.log"
        try:
            if p.stat().st_size > 5_000_000:
                os.replace(p, d / "server.old.log")
        except OSError:  # no log yet, or another host still holds it open
            pass
        LOG = open(p, "ab", buffering=0)
    except OSError:
        LOG = None


def log(msg: str) -> None:
    try:
        if LOG:
            LOG.write(f"[host {time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n".encode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        pass


def fatal(text: str) -> None:
    log("FATAL: " + text)
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text[:900], NAME, 0x10)
        except Exception:  # noqa: BLE001
            pass


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never send localhost traffic through a system proxy


def api(port: int, path: str, post: bool = False, timeout: float = 1.5):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}" if post else None,
                                 headers={"X-ImageLoom": "1", "Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception:  # noqa: BLE001
        return None


def alive(port: int) -> bool:
    return bool((api(port, "/api/status") or {}).get("ok"))


def read_info() -> dict:
    try:
        return json.loads((DATA / "server.json").read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return {}


def free_port(preferred: int = 7870) -> int:
    """7870 keeps the page's localStorage (it is per origin); otherwise the next free port, otherwise any."""
    for p in (*range(preferred, preferred + 60), 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return s.getsockname()[1]
        except OSError:
            pass
        finally:
            s.close()
    return preferred


class Server:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.label = ""

    def start(self, label: str) -> None:
        self.label, self.port = label, free_port()
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
        env.update(IMAGELOOM_PORT=str(self.port), IMAGELOOM_HOST=label, IMAGELOOM_ENGINE_DIR=str(ENGINE), IMAGELOOM_HOME=str(DATA),
                   IMAGELOOM_PARENT_PID=str(os.getpid()), PYTHONUTF8="1", PYTHONNOUSERSITE="1")
        log(f"starting server: {sys.executable} {SERVER_PY} (port {self.port}, host label {label})")
        self.proc = subprocess.Popen([sys.executable, "-u", str(SERVER_PY)], cwd=str(SERVER_PY.parent), env=env, stdin=DEVNULL,
                                     stdout=LOG or DEVNULL, stderr=subprocess.STDOUT, creationflags=NOWIN)

    def wait_ready(self, timeout: float = 90) -> bool:
        t0 = time.time()
        while self.proc and self.proc.poll() is None and time.time() - t0 < timeout:
            info = read_info()
            mine = info.get("pid") == self.proc.pid and info.get("port")  # the server may have moved to another port
            if mine:
                self.port = int(info["port"])
            if (mine or time.time() - t0 > 20) and alive(self.port):
                return True
            time.sleep(0.3)
        return False

    def stop(self) -> None:
        p = self.proc
        if not p or p.poll() is not None:
            return
        if api(self.port, "/api/quit", post=True, timeout=3) is not None:
            try:
                p.wait(5)
                return
            except subprocess.TimeoutExpired:
                log("server did not exit after /api/quit")
        log("killing the server process tree")
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdin=DEVNULL, capture_output=True, creationflags=NOWIN)
        else:
            p.kill()
        try:
            p.wait(3)
        except subprocess.TimeoutExpired:
            pass


def webview2_installed() -> bool:
    """Evergreen WebView2 runtime registered for the machine or the user (the same keys the installer checks)."""
    try:
        import winreg
    except ImportError:
        return False
    guid = r"\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + guid), (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE" + guid),
                      (winreg.HKEY_CURRENT_USER, "Software" + guid), (winreg.HKEY_CURRENT_USER, r"Software\WOW6432Node" + guid)):
        try:
            with winreg.OpenKey(root, sub) as k:
                if str(winreg.QueryValueEx(k, "pv")[0]) not in ("", "0.0.0.0"):
                    return True
        except OSError:
            pass
    return False


def load_webview():
    """-> (module, '') or (None, reason). The choice is made BEFORE the server starts: its host label tells the UI whether to show a quit button."""
    if not webview2_installed():
        return None, "WebView2 runtime not found"
    try:
        import webview
        return webview, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"import webview failed: {exc!r}"


def failure_page() -> str:
    try:
        tail = "\n".join((DATA / "logs" / "server.log").read_text(encoding="utf-8", errors="replace").splitlines()[-14:])
    except OSError:
        tail = ""
    return PAGE.replace("@@", f"<h2>{html.escape(tr('server_failed_title'))}</h2><pre style='background:#1b1b19;padding:14px;border-radius:10px;"
                              f"white-space:pre-wrap;color:#c9c9c2'>{html.escape(tail)}</pre><p>{html.escape(tr('log_label'))}: {html.escape(str(DATA / 'logs' / 'server.log'))}</p>")


def run_webview(webview, srv: Server | None, port: int) -> bool:
    """Show the window and block until it is closed. False = pywebview / WebView2 could not be used (caller falls back)."""
    for key in ("ALLOW_DOWNLOADS", "OPEN_EXTERNAL_LINKS_IN_BROWSER"):
        try:
            webview.settings[key] = True
        except Exception:  # noqa: BLE001
            pass
    state = {"bad": False}
    win = webview.create_window(NAME, url=None if srv else f"http://127.0.0.1:{port}", html=PAGE.replace("@@", SPINNER) if srv else None,
                                width=1360, height=880, min_size=(900, 620), background_color="#111110", text_select=True, zoomable=True)

    def closing():  # runs on the UI thread; only the host that owns the server asks (closing the window stops the job)
        try:
            st = srv and api(srv.port, "/api/status") or {}
            queued = int(st.get("queued") or 0)
            if isinstance(st.get("running"), str) or queued > 0:
                ok = win.create_confirmation_dialog(tr("busy_title"), tr("busy_text", queued=queued))
                return False if ok is False else True
        except Exception:  # noqa: BLE001
            pass
        return True

    def boot():
        if getattr(webview, "renderer", "edgechromium") != "edgechromium":  # MSHTML (old IE engine) cannot run this UI
            log(f"pywebview picked renderer {webview.renderer!r}, not WebView2")
            state["bad"] = True
            win.destroy()
        elif srv:
            if srv.wait_ready():
                win.load_url(f"http://127.0.0.1:{srv.port}")
            else:
                win.load_html(failure_page())

    win.events.closing += closing
    try:
        webview.start(boot, icon=str(ICON) if ICON.is_file() else None, private_mode=False, storage_path=str(DATA / "webview"))
    except Exception:  # noqa: BLE001
        log("pywebview failed:\n" + traceback.format_exc())
        return False
    return not state["bad"]


def find_edge() -> str | None:
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if os.environ.get(var):
            p = Path(os.environ[var]) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.is_file():
                return str(p)
    return shutil.which("msedge")


def open_browser(url: str) -> None:
    edge = find_edge()
    try:
        if edge:
            subprocess.Popen([edge, f"--app={url}", "--window-size=1360,880"], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL)
            log(f"UI opened with Microsoft Edge --app ({edge})")
            return
    except OSError as exc:
        log(f"msedge failed: {exc!r}")
    webbrowser.open(url)
    log("UI opened in the default browser")


def main() -> None:
    open_log()
    info = read_info()
    existing = int(info.get("port") or 0) if info.get("port") and alive(int(info["port"])) else 0  # single instance
    webview, why = load_webview()
    srv = None if existing else Server()
    if srv:
        srv.start("windows-app" if webview else "windows-edge")
    port = existing or srv.port
    log(f"{NAME} host: {'attached to the running server on port %d' % existing if existing else 'owns the server'}")
    shown = False
    if webview:
        log("mode: pywebview window (WebView2)")
        shown = run_webview(webview, srv, port)
        why = "" if shown else (why or "pywebview could not start the window")
    if not shown:
        log(f"mode: Microsoft Edge / browser fallback ({why})")
        if srv and srv.label != "windows-edge":  # the UI shows its own quit button only for the windows-edge label
            srv.stop()
            srv.start("windows-edge")
        if srv and not srv.wait_ready():
            return fatal(tr("server_failed", log=DATA / "logs" / "server.log"))
        open_browser(f"http://127.0.0.1:{srv.port if srv else port}")
        if srv and srv.proc:
            srv.proc.wait()  # the UI's Quit button (POST /api/quit) ends the server, and with it this host
    if srv:
        srv.stop()


if __name__ == "__main__":
    code = 0
    try:
        main()
    except Exception:  # noqa: BLE001
        code = 1
        fatal(tr("startup_error") + traceback.format_exc()[-700:])
    os._exit(code)  # never wait for a lingering non-daemon GUI thread
