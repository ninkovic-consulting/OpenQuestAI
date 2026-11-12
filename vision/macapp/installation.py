"""The built app on this Mac: installing it, opening it, and its login item.

The login item is the app's own (`<app> --login-item on|off|status`), so
`vision setup` and `vision doctor` see the same thing as the app's menu.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Literal

from vision.core.config import Config
from vision.macapp.bundle import DIST, Runner, app_name, built_app

LoginState = Literal["enabled", "requires-approval", "off"]
LOGIN_STATES: dict[str, LoginState] = {
    "enabled": "enabled", "requires-approval": "requires-approval", "off": "off"
}


def applications_dir() -> Path:
    return Path.home() / "Applications"


def installed_app(config: Config, applications: Path | None = None) -> Path:
    return (applications or applications_dir()) / f"{app_name(config)}.app"


def install(config: Config, *, dist: Path = DIST, applications: Path | None = None) -> Path:
    """Copy `dist/<name>.app` into `~/Applications`, replacing an older copy."""
    source = built_app(config, dist)
    if not source.is_dir():
        raise FileNotFoundError(f"{source} is not built yet; run `vision app build` first.")
    target = installed_app(config, applications)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)
    return target


def app_to_open(config: Config, *, dist: Path = DIST, applications: Path | None = None) -> Path:
    """The installed app if there is one, else the one in `dist/`."""
    installed = installed_app(config, applications)
    if installed.is_dir():
        return installed
    built = built_app(config, dist)
    if built.is_dir():
        return built
    raise FileNotFoundError("The app is not built yet; run `vision app build` first.")


def open_app(app: Path, run: Runner = subprocess.run) -> None:
    run(["/usr/bin/open", str(app)], check=True)


def executable(config: Config, app: Path) -> Path:
    return app / "Contents" / "MacOS" / app_name(config)


def login_item(
    config: Config, app: Path, verb: Literal["on", "off", "status"], run: Runner = subprocess.run
) -> LoginState:
    """Ask the app to turn its login item on or off, or report it. No window opens."""
    done = run(
        [str(executable(config, app)), "--login-item", verb],
        capture_output=True, text=True, timeout=15, check=False,
    )
    answer = done.stdout.strip()
    state = LOGIN_STATES.get(answer)
    if done.returncode != 0 or state is None:
        raise RuntimeError(done.stderr.strip() or f"the app answered {answer!r}")
    return state
