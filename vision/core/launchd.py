"""The LaunchAgent that keeps the daemon running after login.

`plist_bytes` builds the plist (pure, tested). `install` writes it to
`~/Library/LaunchAgents` and loads it with `launchctl bootstrap`; `uninstall`
unloads and removes it. Both are run by the user via the CLI; Delete all data
(`vision.settings.erase`) also removes the agent, through `remove_plist` and
`unload` when the daemon runs as the agent itself, so it can answer before it
is stopped. Every `launchctl` call goes through `_launchctl`, which the tests
replace.
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


def _launchctl(args: list[str], *, check: bool) -> None:
    subprocess.run(["launchctl", *args], check=check)


def installed() -> bool:
    return plist_path().exists()


def is_this_process() -> bool:
    """True when this process is the agent's own: launchd names the job in `XPC_SERVICE_NAME`."""
    return os.environ.get("XPC_SERVICE_NAME") == LABEL


def install(config: Config, *, port: int | None = None) -> Path:
    """Write the plist and load it. Replaces an existing agent with the same label."""
    config.paths.logs.mkdir(parents=True, exist_ok=True)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _launchctl(["bootout", f"{_domain()}/{LABEL}"], check=False)
    path.write_bytes(plist_bytes(config, port=port))
    _launchctl(["bootstrap", _domain(), str(path)], check=True)
    return path


def unload() -> None:
    """Stop the agent and forget it until the next login; when this process is the agent, it ends."""
    _launchctl(["bootout", f"{_domain()}/{LABEL}"], check=False)


def remove_plist() -> Path:
    """Remove the plist only; a loaded agent keeps running until `unload` or logout."""
    path = plist_path()
    path.unlink(missing_ok=True)
    return path


def uninstall() -> Path:
    """Unload the agent and remove its plist."""
    unload()
    return remove_plist()
