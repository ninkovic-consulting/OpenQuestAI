"""Where Vision's own files are: the default house, the tool catalog and the window.

From a source checkout they are in the repository. In the standalone Mac app
the shell sets `VISION_RESOURCES` to the bundle's `Contents/Resources`, which
holds `house/` and `web/dist/` beside the bundled Python. User data is never
here: it lives in `$VISION_HOME` (section 4.1 of the spec).
"""

from __future__ import annotations

import os
from pathlib import Path

ENV = "VISION_RESOURCES"
SOURCE_ROOT = Path(__file__).resolve().parents[2]
"""The repository, when running from a checkout."""


def standalone() -> bool:
    """True when running inside the standalone app."""
    return bool(os.environ.get(ENV))


def root() -> Path:
    env = os.environ.get(ENV)
    return Path(env) if env else SOURCE_ROOT


def house_dir() -> Path:
    """The default house, the tool catalog and the agents' personas."""
    return root() / "house"


def web_dist() -> Path:
    """The built window."""
    return root() / "web" / "dist"


def env_file() -> Path | None:
    """The `.env` file to read the API key from; never one in the standalone app."""
    if standalone():
        return None
    override = os.environ.get("VISION_ENV_FILE")
    return Path(override).expanduser() if override else SOURCE_ROOT / ".env"
