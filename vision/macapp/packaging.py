"""`vision app package`: the standalone app as one zip, for moving to another Mac."""

from __future__ import annotations

import platform
import plistlib
import subprocess
from pathlib import Path

from vision import display_version
from vision.core.config import Config
from vision.macapp.bundle import DIST, AppBuildError, Runner, app_name, built_app


def is_standalone(app: Path) -> bool:
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    return info.get("VisionStandalone") is True


def package_path(config: Config, dist: Path = DIST) -> Path:
    return dist / f"{app_name(config)}-{display_version()}-macos-{platform.machine()}.zip"


def package(config: Config, *, dist: Path = DIST, run: Runner = subprocess.run) -> Path:
    """Zip `dist/<name>.app` with `ditto`, which keeps the signatures intact."""
    app = built_app(config, dist)
    if not app.is_dir() or not is_standalone(app):
        raise AppBuildError(
            "Only the standalone app can move to another Mac; "
            "run `vision app build --standalone` first."
        )
    out = package_path(config, dist)
    out.unlink(missing_ok=True)
    argv = ["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(out)]
    if run(argv, check=False).returncode != 0:
        raise AppBuildError("Zipping the app failed; its output is above.")
    return out
