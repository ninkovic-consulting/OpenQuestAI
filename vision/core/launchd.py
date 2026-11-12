"""The LaunchAgent that keeps the daemon running after login.

`plist_bytes` builds the plist (pure, tested). `install` writes it to
`~/Library/LaunchAgents` and loads it with `launchctl bootstrap`; `uninstall`
unloads and removes it. Both are only ever run by the user via the CLI.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from vision.core.config import Config

LABEL = "com.vision.daemon"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def program_arguments(port: int | None = None) -> list[str]:
    """Run this interpreter's `vision` package, so the venv is always the right one."""
    args = [sys.executable, "-m", "vision", "run"]
    if port is not None:
        args += ["--port", str(port)]
    return args


def plist_bytes(config: Config, *, port: int | None = None) -> bytes:
    logs = config.paths.logs
    plist = {
        "Label": LABEL,
        "ProgramArguments": program_arguments(port),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "WorkingDirectory": str(config.paths.home),
        "EnvironmentVariables": {
            "VISION_HOME": str(config.paths.home),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        "StandardOutPath": str(logs / "daemon.out.log"),
        "StandardErrorPath": str(logs / "daemon.err.log"),
    }
    return plistlib.dumps(plist)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(config: Config, *, port: int | None = None) -> Path:
    """Write the plist and load it. Replaces an existing agent with the same label."""
    config.paths.logs.mkdir(parents=True, exist_ok=True)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], check=False)
    path.write_bytes(plist_bytes(config, port=port))
    subprocess.run(["launchctl", "bootstrap", _domain(), str(path)], check=True)
    return path


def uninstall() -> Path:
    """Unload the agent and remove its plist."""
    path = plist_path()
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], check=False)
    path.unlink(missing_ok=True)
    return path
