"""Everything the checks and the setup touch outside this process, behind one interface.

The checks only read. The setup's changes (storing the key, downloads, the
microphone check, building the window and the app, the login items) are
separate methods so a test can fake all of it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import platform
import subprocess
from pathlib import Path
from typing import Literal, Protocol

from vision import macapp
from vision.core import launchd, resources, secrets
from vision.core.config import Config
from vision.core.programs import find_program
from vision.setup import hf_cache

KeyVerdict = Literal["accepted", "refused", "unreachable", "none"]
WEB_DIR = resources.SOURCE_ROOT / "web"
"""Where the window is built from; only in a source checkout."""
SPEECH_SKIP = {"spacy/en_core_web_sm": ["*.whl"]}
"""Files left out of a repo's download, as the voice itself fetches it."""
RUN_TIMEOUT_S = 15.0


class System(Protocol):
    # ------------------------------------------------------------ read only
    def find(self, name: str) -> Path | None: ...
    def exit_code(self, argv: list[str]) -> int | None: ...
    def output(self, argv: list[str]) -> str | None: ...
    def has_module(self, name: str) -> bool: ...
    def cached_size(self, repo: str, needs: str = "*") -> int | None: ...
    def python_version(self) -> str: ...
    def api_key_source(self) -> str | None: ...
    def verify_key(self) -> KeyVerdict: ...
    def agent_installed(self) -> bool: ...
    def agent_loaded(self) -> bool: ...
    def window_built(self) -> bool: ...
    def swiftc(self) -> Path | None: ...
    def app_built(self, config: Config) -> bool: ...
    def app_installed(self, config: Config) -> bool: ...
    def app_login_item(self, config: Config) -> macapp.LoginState | None: ...

    # ------------------------------------------------------------ changes, setup only
    def store_key(self, key: str) -> None: ...
    def download_size(self, repos: list[str]) -> int | None: ...
    def download(self, repos: list[str]) -> None: ...
    def download_local_model(self, config: Config) -> None: ...
    def mic_check(self) -> None: ...
    def build_window(self) -> bool: ...
    def install_agent(self, config: Config) -> Path: ...
    def build_app(self, config: Config) -> Path: ...
    def install_app(self, config: Config) -> Path: ...
    def set_app_login_item(self, config: Config, on: bool) -> macapp.LoginState: ...


class MacSystem:
    """The real Mac."""

    def find(self, name: str) -> Path | None:
        return find_program(name)

    def exit_code(self, argv: list[str]) -> int | None:
        program = self.find(argv[0])
        if program is None:
            return None
        try:
            done = subprocess.run(
                [str(program), *argv[1:]],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=RUN_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.returncode

    def output(self, argv: list[str]) -> str | None:
        program = self.find(argv[0])
        if program is None:
            return None
        try:
            done = subprocess.run(
                [str(program), *argv[1:]],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    def has_module(self, name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    def cached_size(self, repo: str, needs: str = "*") -> int | None:
        return hf_cache.cached_size(repo, needs=needs)

    def python_version(self) -> str:
        return platform.python_version()

    def api_key_source(self) -> str | None:
        return secrets.api_key_source()

    def verify_key(self) -> KeyVerdict:
        """Ask the API to list one model with the stored key; listing models is not billed."""
        import anthropic

        key = secrets.get_api_key()
        if key is None:
            return "none"
        try:
            with anthropic.Anthropic(api_key=key, timeout=15.0, max_retries=0) as client:
                client.models.list(limit=1)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            return "refused"
        except anthropic.APIError:
            return "unreachable"
        return "accepted"

    def agent_installed(self) -> bool:
        return launchd.plist_path().is_file()

    def agent_loaded(self) -> bool:
        target = f"gui/{os.getuid()}/{launchd.LABEL}"
        return self.exit_code(["launchctl", "print", target]) == 0

    def window_built(self) -> bool:
        return (resources.web_dist() / "index.html").is_file()

    def swiftc(self) -> Path | None:
        return macapp.find_swiftc()

    def app_built(self, config: Config) -> bool:
        return macapp.built_app(config).is_dir()

    def app_installed(self, config: Config) -> bool:
        return macapp.installed_app(config).is_dir()

    def app_login_item(self, config: Config) -> macapp.LoginState | None:
        """The installed app's login item; None when it is not installed or cannot say."""
        app = macapp.installed_app(config)
        if not app.is_dir():
            return None
        try:
            return macapp.login_item(config, app, "status")
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return None

    def store_key(self, key: str) -> None:
        secrets.store_api_key(key)

    def download_size(self, repos: list[str]) -> int | None:
        from fnmatch import fnmatch

        try:
            from huggingface_hub import HfApi
        except ImportError:
            return None
        api = HfApi()
        total = 0
        try:
            for repo in repos:
                skip = SPEECH_SKIP.get(repo, [])
                info = api.model_info(repo, files_metadata=True)
                total += sum(
                    s.size or 0
                    for s in info.siblings or []
                    if not any(fnmatch(s.rfilename, p) for p in skip)
                )
        except Exception:  # offline or the Hub is down: the size is just unknown
            return None
        return total

    def download(self, repos: list[str]) -> None:
        from huggingface_hub import snapshot_download

        for repo in repos:
            snapshot_download(repo, ignore_patterns=SPEECH_SKIP.get(repo))

    def download_local_model(self, config: Config) -> None:
        from vision.brains.mlx_local import setup_model

        setup_model(config.brain.local_model)

    def mic_check(self) -> None:
        from vision.voice.check import check

        asyncio.run(check(3.0))

    def build_window(self) -> bool:
        npm = self.find("npm")
        if npm is None:
            return False
        env = {**os.environ, "PATH": f"{npm.parent}{os.pathsep}{os.environ.get('PATH', '')}"}
        for args in (["ci"], ["run", "build"]):
            if subprocess.run([str(npm), *args], cwd=WEB_DIR, env=env, check=False).returncode:
                return False
        return True

    def install_agent(self, config: Config) -> Path:
        return launchd.install(config)

    def build_app(self, config: Config) -> Path:
        return macapp.build(config)

    def install_app(self, config: Config) -> Path:
        return macapp.install(config)

    def set_app_login_item(self, config: Config, on: bool) -> macapp.LoginState:
        return macapp.login_item(config, macapp.installed_app(config), "on" if on else "off")
