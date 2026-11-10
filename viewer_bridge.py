"""Secure short-lived handoff of editor calculations to the integrated VIEWER.

No user data is placed inside browser query strings. Only an unpredictable token
travels to the new window; the project snapshot stays in the server temp directory.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import gettempdir
import secrets
import time

from project_file import save_project, load_project

ROOT = Path(gettempdir()) / "coveragediagrams_viewer_handoffs"
TTL_SECONDS = 6 * 3600


def _cleanup():
    ROOT.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for item in ROOT.glob("*.cdproj"):
        try:
            if now - item.stat().st_mtime > TTL_SECONDS:
                item.unlink(missing_ok=True)
        except OSError:
            continue


def publish(result, levels, obstacles, source_ui=None):
    """Create a portable editor snapshot for independent browser sessions."""
    _cleanup()
    data = save_project(result, levels=list(levels), obstacles=list(obstacles),
                        source_ui=source_ui or {})
    token = secrets.token_urlsafe(32)
    target = ROOT / (token + ".cdproj")
    with target.open("xb") as stream:
        stream.write(data)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return token


def acquire(token):
    """Only accept random URL-safe tokens; validate the archive before use."""
    if not isinstance(token, str) or len(token) > 128 or not token or any(
        c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for c in token
    ):
        raise ValueError("Neplatný identifikátor VIEWER snapshotu.")
    target = ROOT / (token + ".cdproj")
    if not target.is_file():
        raise FileNotFoundError("Snapshot nebyl nalezen nebo již vypršel.")
    if time.time() - target.stat().st_mtime > TTL_SECONDS:
        target.unlink(missing_ok=True)
        raise FileNotFoundError("Platnost snapshotu vypršela; otevři VIEWER z EDITORU znovu.")
    return load_project(target.read_bytes())
