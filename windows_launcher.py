"""Windows desktop launcher for the existing Streamlit radar application.

The parent creates a native WebView2 window; a child process of the same
bundled executable hosts Streamlit on loopback only.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

SERVER_FLAG = "--coverage-streamlit-server"


def app_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def log_file() -> Path:
    folder = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "COVERAGEDIAGRAMS" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "desktop-startup.log"


def run_server(port: int) -> None:
    from streamlit.web import bootstrap

    script = app_root() / "streamlit_app.py"
    if not script.is_file():
        raise FileNotFoundError(f"Missing bundled Streamlit application: {script}")
    # Some Streamlit components use the current working directory for config.
    os.chdir(app_root())
    sys.argv = ["streamlit", "run", str(script)]
    bootstrap.run(str(script), False, [], {
        "server.port": port,
        "server.address": "127.0.0.1",
        "server.headless": True,
        "server.fileWatcherType": "none",
        "browser.gatherUsageStats": False,
    })


def wait_until_ready(port: int, process: subprocess.Popen, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (OSError, URLError):
            pass
        time.sleep(0.35)
    return False


def show_error(message: str) -> None:
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, message, "COVERAGEDIAGRAMS Desktop", 0x10)


def run_desktop() -> None:
    import webview

    port = find_free_port()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    logfile = log_file()
    with logfile.open("a", encoding="utf-8") as output:
        output.write(f"\n--- Launch {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        output.flush()
        proc = subprocess.Popen(
            [sys.executable, SERVER_FLAG, str(port)],
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=flags,
            cwd=str(app_root()),
        )
        try:
            if not wait_until_ready(port, proc):
                show_error(f"Radar server did not start.\nCheck log:\n{logfile}")
                return
            window = webview.create_window(
                "COVERAGEDIAGRAMS · Radar Coverage",
                f"http://127.0.0.1:{port}",
                width=1550, height=950, min_size=(1024, 680),
                background_color="#061523",
            )
            webview.start(gui="edgechromium", debug=False)
        except Exception as exc:
            show_error(f"Unable to open desktop window: {exc}\nLog: {logfile}\n\nInstall Microsoft Edge WebView2 Runtime if needed.")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == SERVER_FLAG:
        run_server(int(sys.argv[2]))
    else:
        run_desktop()


if __name__ == "__main__":
    main()
