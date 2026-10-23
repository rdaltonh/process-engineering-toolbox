"""Desktop launcher for the Process Engineering Toolbox (Windows).

Started by the desktop / Start-menu shortcut via .venv\\Scripts\\pythonw.exe,
so no console window appears. It:

1. Reuses a toolbox server already running on PORT, or starts one hidden
   (output goes to %LOCALAPPDATA%\\ProcessToolbox\\server.log). Before
   starting one, it re-runs `pip install -e .[dev]` if pyproject.toml has
   changed since the last install, so pulled dependency changes apply
   without a reinstall.
2. Opens the toolbox in its own app window (Edge or Chrome --app mode, with a
   dedicated browser profile so it behaves like a separate program).
3. When that window closes, stops the server, but only if this launcher
   started it. A server someone else started is left alone.

If neither Edge nor Chrome is found it falls back to the default browser and
leaves the server running (there is no window to watch).
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8501
URL = f"http://localhost:{PORT}"
HEALTH_URL = f"{URL}/_stcore/health"
STARTUP_TIMEOUT_S = 90

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ProcessToolbox"
LOG_PATH = DATA_DIR / "server.log"
PIP_LOG_PATH = DATA_DIR / "pip.log"
PROFILE_DIR = DATA_DIR / "browser-profile"

VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PYPROJECT = ROOT / "pyproject.toml"
# Kept inside the venv so a rebuilt .venv always triggers a fresh sync.
# Install.ps1 writes the same SHA-256 (hex) after its own pip install.
DEPS_STAMP = ROOT / ".venv" / "toolbox-deps.sha256"

BROWSER_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010


def error_box(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "Process Engineering Toolbox", 0x10)


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
         "--log", str(PIP_LOG_PATH), "-e", ".[dev]"],
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
        # If our server died (e.g. the port was taken by a server another launch
        # just started), give that other server a short grace period to answer.
        if proc.poll() is not None:
            deadline = min(deadline, time.monotonic() + 15)
        time.sleep(0.5)
    return False


def find_browser() -> Path | None:
    return next((p for p in BROWSER_CANDIDATES if p.is_file()), None)


def open_app_window(browser: Path) -> subprocess.Popen:
    return subprocess.Popen([
        str(browser),
        f"--app={URL}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1500,950",
    ])


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not VENV_PYTHON.is_file():
        error_box(f"No Python environment found at {ROOT / '.venv'}.\n\nRun desktop\\Install.ps1 first.")
        return 1

    server: subprocess.Popen | None = None
    if not server_healthy():
        # Only sync when no server is running: never pip install under a live server.
        if not sync_dependencies():
            error_box(
                "Updating the toolbox's Python packages failed.\n\n"
                f"See the log:\n{PIP_LOG_PATH}\n\n"
                'Or run manually:  .venv\\Scripts\\python -m pip install -e ".[dev]"'
            )
            return 1
        server = start_server()
        if not wait_for_server(server):
            stop_server(server)
            error_box(f"The toolbox server did not start.\n\nSee the log:\n{LOG_PATH}")
            return 1
        if server.poll() is not None:
            server = None  # another launch's server answered; not ours to stop

    browser = find_browser()
    if browser is None:
        webbrowser.open(URL)
        return 0

    open_app_window(browser).wait()
    # The first launch owns the browser process; a second launch's browser call
    # hands off to it and returns at once, so only stop the server we started.
    if server is not None:
        stop_server(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
