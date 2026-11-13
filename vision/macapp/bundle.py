"""Building the Mac app: where it goes, its Info.plist, and the call to `macos/build.sh`.

The app is a small Swift shell around the daemon and the web window. The thin
build (the default, for development) writes the project path, the port and
the home into Info.plist so the app runs the project's `.venv`. The standalone
build (`vision.macapp.standalone`) hands over a payload of Python, packages,
house and window to put inside the bundle, and the app uses `~/.vision`.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

from vision import display_version
from vision.core.config import Config
from vision.core.resources import SOURCE_ROOT as REPO_ROOT

BUNDLE_ID = "org.openquestai.vision"
MIN_MACOS = "14.0"
"""macOS 14 is the first that accepts an IP address in the ATS exception list."""
MACOS_DIR = REPO_ROOT / "macos"
TEMPLATE = MACOS_DIR / "Info.plist"
BUILD_SCRIPT = MACOS_DIR / "build.sh"
ICON = REPO_ROOT / "assets" / "icon" / "Vision.icns"
DIST = REPO_ROOT / "dist"
BUILD_NUMBER_ENV = "VISION_BUILD_NUMBER"
"""The pipeline's run number; a build made without it is build 0."""
STANDALONE_HOME = "~/.vision"
"""Expanded by the app on the Mac it runs on, never on the one that built it."""

Runner = Callable[..., subprocess.CompletedProcess[str]]


class AppBuildError(Exception):
    """The app could not be built; the message says why and what to do."""


def app_name(config: Config) -> str:
    """The assistant's name, safe as a file name."""
    name = re.sub(r'[/:\\"\x00-\x1f]', "-", config.assistant.name).strip(" .")
    return name or "Vision"


def built_app(config: Config, dist: Path = DIST) -> Path:
    return dist / f"{app_name(config)}.app"


def find_swiftc(run: Runner = subprocess.run) -> Path | None:
    """The Swift compiler through `xcrun`; `/usr/bin/swiftc` alone may be the install stub."""
    try:
        done = run(["xcrun", "--find", "swiftc"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    path = Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None
    return path if path is not None and path.is_file() else None


def build_number(environ: Mapping[str, str] | None = None) -> str:
    """The build number, from `VISION_BUILD_NUMBER`; `0` for a build made by hand.

    Apple wants `CFBundleVersion` to be period-separated integers, so a whole number only.
    """
    value = (os.environ if environ is None else environ).get(BUILD_NUMBER_ENV, "").strip()
    if not value:
        return "0"
    if not (value.isascii() and value.isdigit()):
        raise AppBuildError(f"{BUILD_NUMBER_ENV} must be a whole number, not {value!r}.")
    return str(int(value))


def info_plist(
    config: Config,
    *,
    project: Path = REPO_ROOT,
    template: Path = TEMPLATE,
    icon: bool = True,
    standalone: bool = False,
    number: str | None = None,
) -> bytes:
    """The rendered Info.plist; without an icon the system's default icon is used.

    `CFBundleShortVersionString` is the version as people read it (`0.1.0-beta`, which
    the Settings page shows) and `CFBundleVersion` the build number.

    A standalone app names no project and uses `~/.vision` on whichever Mac it runs.
    """
    name = app_name(config)
    values = {
        "name": config.assistant.name,
        "executable": name,
        "bundle_id": BUNDLE_ID,
        "version": display_version(),
        "build": number if number is not None else build_number(),
        "min_macos": MIN_MACOS,
        "project": "" if standalone else str(project),
        "home": STANDALONE_HOME if standalone else str(config.paths.home),
        "port": str(config.server.port),
        "standalone": "true" if standalone else "false",
    }
    text = Template(template.read_text(encoding="utf-8")).substitute(
        {key: escape(value) for key, value in values.items()}
    )
    info = plistlib.loads(text.encode())
    if not icon:
        del info["CFBundleIconFile"]
    return plistlib.dumps(info)


def build(
    config: Config,
    *,
    project: Path = REPO_ROOT,
    dist: Path = DIST,
    icon: Path = ICON,
    payload: Path | None = None,
    run: Runner = subprocess.run,
) -> Path:
    """Compile and assemble `dist/<name>.app`, signed ad hoc. Returns its path.

    With a `payload` (a folder of signed files for `Contents/Resources`), the app
    is standalone; without one it runs the project's `.venv`.
    """
    swiftc = find_swiftc(run)
    if swiftc is None:
        raise AppBuildError(
            "The Swift compiler (swiftc) was not found. Install Xcode, or the Command Line "
            "Tools with `xcode-select --install`, then run `vision app build` again."
        )
    python = project / ".venv" / "bin" / "python"
    if payload is None and not python.exists():
        raise AppBuildError(f"There is no {python}; run `uv sync --all-extras` first.")
    has_icon = icon.is_file()
    app = built_app(config, dist)
    dist.mkdir(parents=True, exist_ok=True)
    plist = dist / "Info.plist"
    plist.write_bytes(
        info_plist(config, project=project, icon=has_icon, standalone=payload is not None)
    )
    argv = [
        "/bin/sh", str(BUILD_SCRIPT), str(app), str(plist), app_name(config), BUNDLE_ID, MIN_MACOS
    ]
    if has_icon:
        argv.append(str(icon))
    try:
        env = {**os.environ, "SWIFTC": str(swiftc)}
        if payload is not None:
            env["PAYLOAD"] = str(payload)
        done = run(argv, env=env, check=False)
    finally:
        plist.unlink(missing_ok=True)
    if done.returncode != 0:
        raise AppBuildError(f"The build failed (exit status {done.returncode}); its output is above.")
    return app
