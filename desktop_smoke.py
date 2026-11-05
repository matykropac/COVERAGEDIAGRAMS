"""Headless smoke test for the packaged local Streamlit backend.

This verifies that bundled resources and the internal loopback server start.
Native GUI automation is intentionally not attempted in GitHub Actions.
"""
from __future__ import annotations
import argparse
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen


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
                with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        print("PASS: packaged Streamlit loopback health")
                        return
            except (OSError, URLError):
                pass
            time.sleep(.5)
        raise RuntimeError("Packaged Streamlit server failed health check within timeout")
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)


if __name__ == "__main__":
    main()
