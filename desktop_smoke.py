"""Headless smoke test for the packaged local Streamlit backend.

This verifies that bundled resources and the internal loopback server start.
Native GUI automation is intentionally not attempted in GitHub Actions.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import build_opener, ProxyHandler


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    port = free_port()
    process = subprocess.Popen([args.binary, "--coverage-streamlit-server", str(port)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        limit = time.monotonic() + args.timeout
        while time.monotonic() < limit:
            if process.poll() is not None:
                output = process.communicate(timeout=5)[0].decode("utf-8", errors="replace")
                raise RuntimeError("Desktop server exited during startup:\n" + output[-5000:])
            try:
                with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        print("PASS: packaged Streamlit loopback health")
                        return
            except (OSError, URLError):
                pass
            time.sleep(.5)
        raise RuntimeError("Packaged Streamlit server failed health check within timeout")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)
        # Show stderr/console output on CI so packaged startup problems are actionable.
        if process.stdout:
            output = process.stdout.read()
            if output:
                print("PACKAGED EXECUTABLE OUTPUT:\\n" +
                      output.decode("utf-8", errors="replace")[-10000:], flush=True)
        if sys.platform == "win32":
            app_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "COVERAGEDIAGRAMS"
        elif sys.platform == "darwin":
            app_dir = Path.home() / "Library" / "Application Support" / "COVERAGEDIAGRAMS"
        else:
            app_dir = Path.home() / ".local" / "share" / "COVERAGEDIAGRAMS"
        logfile = app_dir / "desktop-startup.log"
        if logfile.exists():
            print("DESKTOP STARTUP LOG:\\n" + logfile.read_text(
                encoding="utf-8", errors="replace")[-18000:], flush=True)


if __name__ == "__main__":
    main()
