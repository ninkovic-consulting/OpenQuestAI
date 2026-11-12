"""The local access token at `$VISION_HOME/token` (mode 0600).

Every HTTP request and every WebSocket must present it. It is created on
first run and kept across restarts so an open window can reconnect.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path


def ensure_token(path: Path) -> str:
    """Return the token at `path`, creating it (and its directory) if missing."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_file():
        os.chmod(path, 0o600)
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    os.chmod(path, 0o600)
    return token


def read_token(path: Path) -> str | None:
    """The token, or None if the daemon has never run with this home."""
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def token_matches(expected: str, given: str | None) -> bool:
    return given is not None and hmac.compare_digest(expected.encode(), given.encode())
