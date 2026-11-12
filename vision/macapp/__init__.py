"""The Mac app: a Swift shell (`macos/`) that owns the daemon, the window and a menu bar item.

    app = build(config)              # dist/<name>.app, signed ad hoc, runs the .venv
    app = build_standalone(config)   # the same, with Python and everything inside
    package(config)                  # the standalone app as a zip
    install(config)                  # into ~/Applications
    open_app(app_to_open(config))
"""

from __future__ import annotations

from vision.macapp.bundle import AppBuildError, app_name, build, built_app, find_swiftc
from vision.macapp.installation import (
    LoginState,
    app_to_open,
    install,
    installed_app,
    login_item,
    open_app,
)
from vision.macapp.packaging import package
from vision.macapp.standalone import build_standalone

__all__ = [
    "AppBuildError",
    "LoginState",
    "app_name",
    "app_to_open",
    "build",
    "build_standalone",
    "built_app",
    "find_swiftc",
    "install",
    "installed_app",
    "login_item",
    "open_app",
    "package",
]
