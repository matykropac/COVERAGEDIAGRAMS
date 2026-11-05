"""Cross-platform native desktop shell for the COVERAGEDIAGRAMS Streamlit engine.

The window is native (Edge WebView2 on Windows, WebKit on macOS). Radar
processing and application state remain local, served on loopback only.
"""
from __future__ import annotations

import multiprocessing
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

SERVER_FLAG = "--coverage-streamlit-server"
APP_TITLE = "COVERAGEDIAGRAMS · Radar Coverage"


def app_root() -> Path:
    """Find resources in development and in a PyInstaller onedir bundle."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def user_data_dir() -> Path:
    if sys.platform == "win32":
        parent = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        parent = Path.home() / "Library" / "Application Support"
    else:
        parent = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    folder = parent / "COVERAGEDIAGRAMS"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def startup_log() -> Path:
    return user_data_dir() / "desktop-startup.log"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def server_options(port: int) -> dict:
    return {
        "server.port": port,
        "server.address": "127.0.0.1",
        "server.headless": True,
        "server.fileWatcherType": "none",
        "server.enableCORS": True,
        "server.enableXsrfProtection": True,
        "browser.gatherUsageStats": False,
        "global.developmentMode": False,
        "client.showErrorDetails": "none",
    }


def run_server(port: int) -> None:
    """Start the same Streamlit app used in Cloud; no separate physics fork."""
    script = app_root() / "streamlit_app.py"
    if not script.is_file():
        raise FileNotFoundError(f"Bundled app script is missing: {script}")
    os.chdir(str(app_root()))
    from streamlit.web import bootstrap

    # Both current python and frozen child process enter this function.
    sys.argv = ["streamlit", "run", str(script)]
    bootstrap.run(str(script), False, [], server_options(port))


def wait_for_server(port: int, process: subprocess.Popen, seconds: float = 110.) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if process.poll() is not None:
            return False
        try:
            with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1.5) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError, HTTPError):
            pass
        time.sleep(.35)
    return False


def child_command(port: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, SERVER_FLAG, str(port)]
    return [sys.executable, str(Path(__file__).resolve()), SERVER_FLAG, str(port)]


def show_failure(message: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
    elif sys.platform == "darwin":
        # Cocoa may not be available if the GUI failed to initialize.
        import subprocess as sp
        try:
            sp.run(["osascript", "-e",
                    'display alert "COVERAGEDIAGRAMS" message '
                    + json.dumps(message) + ' as critical'], timeout=10, check=False)
        except (OSError, sp.TimeoutExpired):
            print(message, file=sys.stderr)
    else:
        print(message, file=sys.stderr)


def run_desktop() -> None:
    port = free_port()
    path = startup_log()
    # Cap previous logs without risking an unbounded disk fill.
    if path.exists() and path.stat().st_size > 3_000_000:
        path.rename(path.with_suffix(".previous.log"))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with path.open("a", encoding="utf-8") as output:
        output.write(f"\n-- Desktop start {time.strftime('%Y-%m-%d %H:%M:%S')} --\\n")
        output.flush()
        child = subprocess.Popen(
            child_command(port),
            cwd=str(app_root()),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        try:
            if not wait_for_server(port, child):
                show_failure("Local radar engine did not start.\\nLog: " + str(path))
                return
            import webview
            webview.create_window(
                APP_TITLE,
                f"http://127.0.0.1:{port}",
                width=1580, height=960,
                min_size=(1050, 700),
                background_color="#061523",
                confirm_close=False,
            )
            if sys.platform == "win32":
                webview.start(gui="edgechromium", debug=False)
            else:
                webview.start(gui="cocoa", debug=False)
        except Exception as exc:
            show_failure(f"Unable to open desktop app: {exc}\\nLog: {path}")
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=8)


def main() -> None:
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == SERVER_FLAG:
        try:
            port = int(sys.argv[2])
        except ValueError as exc:
            raise SystemExit("Invalid local server port") from exc
        if not 1024 <= port <= 65535:
            raise SystemExit("Invalid local server port")
        run_server(port)
    else:
        run_desktop()


if __name__ == "__main__":
    main()
