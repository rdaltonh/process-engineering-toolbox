"""Desktop launcher for the Process Engineering Toolbox (Windows).

Started by the desktop / Start-menu shortcut via .venv\\Scripts\\pythonw.exe,
so no console window appears. It:

1. Re-runs `pip install -e .[dev,desktop]` if pyproject.toml has changed
   since the last install, so pulled dependency changes apply without a
   reinstall. Skipped while a server is running (never pip under a live one).
2. Opens a native window (pywebview, backed by Edge WebView2) showing a
   "Starting..." page, then reuses a toolbox server already running on PORT
   or starts one hidden (log: %LOCALAPPDATA%\\ProcessToolbox\\server.log)
   and loads it into the window.
3. When the window closes, stops the server, but only if this launcher
   started it. A server someone else started is left alone.

Only one launcher runs at a time; launching again focuses the open window.
If pywebview is unavailable it falls back to the default browser and leaves
the server running (there is no window to watch).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8501
URL = f"http://localhost:{PORT}"
HEALTH_URL = f"{URL}/_stcore/health"
STARTUP_TIMEOUT_S = 90
TITLE = "Process Engineering Toolbox"
# Own taskbar identity, so Windows shows our icon instead of grouping the
# window under pythonw.exe. Install.ps1 stamps the same ID on the shortcuts
# so a pinned shortcut and the running window share one taskbar button.
APP_ID = "ProcessEngineeringToolbox.Desktop"
ICON_PATH = Path(__file__).resolve().parent / "toolbox.ico"

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ProcessToolbox"
LOG_PATH = DATA_DIR / "server.log"
PIP_LOG_PATH = DATA_DIR / "pip.log"
WEBVIEW_STORAGE = DATA_DIR / "webview"  # keeps Streamlit settings (e.g. theme) between runs

VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYPROJECT = ROOT / "pyproject.toml"
PIP_TARGET = ".[dev,desktop]"
# Kept inside the venv so a rebuilt .venv always triggers a fresh sync.
# Install.ps1 writes the same SHA-256 (hex) after its own pip install.
DEPS_STAMP = ROOT / ".venv" / "toolbox-deps.sha256"

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
ERROR_ALREADY_EXISTS = 183

LOADING_HTML = f"""<!doctype html><html><body style="margin:0;height:100vh;display:flex;
align-items:center;justify-content:center;background:#0e1117;color:#fafafa;
font-family:'Segoe UI',sans-serif"><div style="text-align:center">
<div style="font-size:22px;font-weight:600">{TITLE}</div>
<div style="margin-top:10px;opacity:.7">Starting&hellip;</div></div></body></html>"""

_user32 = ctypes.windll.user32
_mutex = None  # held for the life of the process


def error_box(message: str) -> None:
    _user32.MessageBoxW(None, message, TITLE, 0x10)


def error_html(message: str) -> str:
    return LOADING_HTML.replace("Starting&hellip;", message.replace("\n", "<br>"))


def claim_single_instance() -> bool:
    """True if this is the only launcher; otherwise focus the open window."""
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ProcessToolboxLauncher")
    if ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
        return True
    hwnd = _user32.FindWindowW(None, TITLE)
    if hwnd:
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        _user32.SetForegroundWindow(hwnd)
    return False


def sync_dependencies() -> bool:
    """pip install the project again if pyproject.toml changed since the last sync."""
    digest = hashlib.sha256(PYPROJECT.read_bytes()).hexdigest()
    try:
        if DEPS_STAMP.read_text(encoding="ascii").strip().lower() == digest:
            return True
    except OSError:
        pass
    # Visible console so the user sees progress during the (rare) update.
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check",
         "--log", str(PIP_LOG_PATH), "-e", PIP_TARGET],
        cwd=ROOT, creationflags=CREATE_NEW_CONSOLE,
    )
    if result.returncode != 0:
        return False
    DEPS_STAMP.write_text(digest, encoding="ascii")
    return True


def server_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1) as resp:
            return resp.status == 200
    except OSError:
        return False


def start_server() -> subprocess.Popen:
    # python.exe (not pythonw) so Streamlit has real stdio; CREATE_NO_WINDOW hides the console.
    log = LOG_PATH.open("w", encoding="utf-8")
    return subprocess.Popen(
        [str(VENV_PYTHON), "-m", "streamlit", "run", "launcher/app.py",
         "--server.headless", "true", "--server.port", str(PORT),
         "--client.toolbarMode", "minimal"],  # hide the developer "Deploy" button
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def wait_for_server(proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if server_healthy():
            return True
        # If our server died (e.g. the port is taken by something else), give
        # any other server on the port a short grace period to answer.
        if proc.poll() is not None:
            deadline = min(deadline, time.monotonic() + 15)
        time.sleep(0.5)
    return False


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


class ServerOwner:
    """Starts the server if needed and remembers whether it is ours to stop."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    def ensure_running(self) -> bool:
        if server_healthy():
            return True
        self.proc = start_server()
        if not wait_for_server(self.proc):
            self.stop()
            return False
        if self.proc.poll() is not None:
            self.proc = None  # someone else's server answered; not ours to stop
        return True

    def stop(self) -> None:
        if self.proc is not None:
            stop_server(self.proc)
            self.proc = None


def set_window_icon(hwnd: int) -> None:
    """pywebview's Windows backend ignores `icon=`, so set it on the HWND directly."""
    w = ctypes.wintypes
    _user32.LoadImageW.restype = w.HANDLE
    _user32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT]
    _user32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    for which, size in ((1, 32), (0, 16)):  # ICON_BIG, ICON_SMALL
        hicon = _user32.LoadImageW(None, str(ICON_PATH), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if hicon:
            _user32.SendMessageW(hwnd, 0x80, which, hicon)  # WM_SETICON


def run_window(server: ServerOwner) -> None:
    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True  # PDF / project-file download buttons
    # Opens maximized; 1200x800 is the restored size (fits a 1366x768-class work area).
    window = webview.create_window(TITLE, html=LOADING_HTML, width=1200, height=800, maximized=True,
                                   min_size=(900, 600), background_color="#0E1117")

    def on_shown() -> None:
        try:
            set_window_icon(int(window.native.Handle.ToInt64()))
        except Exception:  # cosmetic only
            pass

    def boot() -> None:
        if server.ensure_running():
            window.load_url(URL)
        else:
            window.load_html(error_html(f"The toolbox server did not start.\nSee the log:\n{LOG_PATH}"))

    window.events.shown += on_shown
    webview.start(boot, private_mode=False, storage_path=str(WEBVIEW_STORAGE))


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not VENV_PYTHON.is_file():
        error_box(f"No Python environment found at {ROOT / '.venv'}.\n\nRun desktop\\Install.ps1 first.")
        return 1
    if not claim_single_instance():
        return 0
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    if not server_healthy() and not sync_dependencies():
        error_box(
            "Updating the toolbox's Python packages failed.\n\n"
            f"See the log:\n{PIP_LOG_PATH}\n\n"
            f'Or run manually:  .venv\\Scripts\\python -m pip install -e "{PIP_TARGET}"'
        )
        return 1

    server = ServerOwner()
    try:
        import webview  # noqa: F401  (installed by the "desktop" extra)
    except ImportError:
        if server.ensure_running():
            webbrowser.open(URL)
            return 0
        error_box(f"The toolbox server did not start.\n\nSee the log:\n{LOG_PATH}")
        return 1

    try:
        run_window(server)
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
