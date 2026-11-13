"""Each requirement as a check: what it is, why it matters, whether it is met, how to fix it.

Checks only read. `run_checks` returns them in the order `vision doctor`
shows them; `online=True` also asks the API whether the stored key works.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from vision import macapp
from vision.core import resources
from vision.core.config import Config
from vision.house import HouseError, store
from vision.house.model import HOST
from vision.house.parse import build_layout
from vision.setup.hf_cache import gigabytes
from vision.setup.system import System
from vision.voice.settings import VoiceSettings

Status = Literal["ok", "missing", "optional"]
"""`missing`: something needed is absent. `optional`: something optional is absent or unchecked."""

MIN_PYTHON = (3, 12)
EXTRAS = {
    "local": ("mlx_lm",),
    "voice": ("mlx_audio", "sounddevice"),
    "ui": ("webview",),
}
SPEECH_ESTIMATE = "about 2 GB"
KEY_SOURCES = {
    "keychain": "the macOS Keychain",
    "env_file": "the .env file",
    "environment": "the ANTHROPIC_API_KEY environment variable",
}
MIC_COMMAND = "uv run python -m vision.voice.check"


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    title: str
    needed_for: str
    needed: bool
    """True when Vision cannot work without it; the doctor fails only on these."""
    status: Status
    detail: str
    fix: str
    """What to do when the status is not `ok`; empty when there is nothing to do."""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class About:
    """What a check is, apart from its result."""

    id: str
    title: str
    needed_for: str
    needed: bool

    def result(self, met: bool, detail: str, fix: str = "") -> Check:
        status: Status = "ok" if met else "missing" if self.needed else "optional"
        return Check(
            self.id, self.title, self.needed_for, self.needed, status, detail, "" if met else fix
        )


API_KEY = About("api_key", "Anthropic API key", "the assistant's mind (Claude)", True)
PYTHON = About("python", "uv and Python", "installing and running Vision", True)
EXTRAS_ABOUT = About(
    "extras", "Optional parts", "the local model (local), speech (voice), the window (ui)", False
)
LOCAL = About("local_model", "Local fallback model", "answering when Claude cannot", False)
SPEECH = About("speech_models", "Speech models", "talking by voice", False)
MIC = About("microphone", "Microphone", "talking by voice", False)
GITHUB = About("github", "GitHub CLI", "GitHub work in project rooms", False)
WINDOW = About("window", "The window", "seeing the house (`vision ui`)", False)
APP = About("app", "The Mac app", "opening the house from its own icon, without Terminal", False)
LOGIN = About("login", "Start at login", "keeping Vision running after you log in", False)
HOUSE = About("house", "The house", "rooms, agents and their projects", True)
TAILSCALE = About("tailscale", "Tailscale", "reaching the house from a phone, later", False)


def api_key(config: Config, system: System, *, online: bool = False) -> Check:
    source = system.api_key_source()
    if source is None:
        return API_KEY.result(
            False,
            "no key in the Keychain, a .env file or the environment",
            "run `vision setup` (or `vision auth`) and paste a key from console.anthropic.com",
        )
    where = KEY_SOURCES.get(source, source)
    if not online:
        return API_KEY.result(True, f"stored in {where}; `vision doctor --online` verifies it")
    verdict = system.verify_key()
    if verdict == "refused":
        return API_KEY.result(
            False, f"stored in {where}, but the API refused it", "store another: `vision auth`"
        )
    if verdict == "unreachable":
        return API_KEY.result(True, f"stored in {where}; the API could not be reached to verify it")
    return API_KEY.result(True, f"stored in {where}, and the API accepted it")


def python(config: Config, system: System) -> Check:
    version = system.python_version()
    if resources.standalone():
        return PYTHON.result(True, f"Python {version}, inside the app")
    uv = system.output(["uv", "--version"])
    recent = tuple(int(p) for p in version.split(".")[:2]) >= MIN_PYTHON
    uv_text = " ".join(uv.split()[:2]) if uv else "uv not found"
    return PYTHON.result(
        bool(uv) and recent,
        f"{uv_text}, Python {version}",
        "install uv (`brew install uv`), then `uv sync --all-extras` (Python 3.12 or newer)",
    )


def extras(config: Config, system: System) -> Check:
    have = [name for name, mods in EXTRAS.items() if all(system.has_module(m) for m in mods)]
    lack = [name for name in EXTRAS if name not in have]
    detail = f"installed: {', '.join(have) or 'none'}"
    if lack:
        detail += f"; not installed: {', '.join(lack)}"
    return EXTRAS_ABOUT.result(not lack, detail, "`uv sync --all-extras`")


def local_model(config: Config, system: System) -> Check:
    if config.brain.local_backend != "mlx":
        return LOCAL.result(True, f"served by {config.brain.local_base_url}")
    repo = config.brain.local_model
    size = system.cached_size(repo, "*.safetensors")
    state = f"downloaded, {gigabytes(size)}" if size is not None else "not downloaded"
    return LOCAL.result(size is not None, f"{repo}, {state}", "`vision setup` downloads it")


def speech_models(config: Config, system: System) -> Check:
    repos = VoiceSettings.from_config(config).model_repos()
    sizes = {repo: system.cached_size(repo) for repo in repos}
    missing = [repo for repo, size in sizes.items() if size is None]
    total = sum(size for size in sizes.values() if size is not None)
    if missing:
        have = len(repos) - len(missing)
        detail = f"{have} of {len(repos)} downloaded; missing {', '.join(missing)}"
    else:
        detail = f"all {len(repos)} downloaded, {gigabytes(total)}"
    return SPEECH.result(not missing, detail, f"`vision setup` downloads them ({SPEECH_ESTIMATE})")


def microphone(config: Config, system: System) -> Check:
    return MIC.result(
        False,
        "not checked here: opening it can raise a macOS permission prompt",
        f"`vision setup` offers a three-second check, or run `{MIC_COMMAND}`",
    )


def github(config: Config, system: System) -> Check:
    if system.find("gh") is None:
        fix = "`brew install gh`, then `gh auth login`"
        return GITHUB.result(False, "gh is not installed", fix)
    signed_in = system.exit_code(["gh", "auth", "status"]) == 0
    detail = "installed and signed in" if signed_in else "installed, not signed in"
    return GITHUB.result(signed_in, detail, "`gh auth login`")


def window(config: Config, system: System) -> Check:
    if system.window_built():
        return WINDOW.result(True, "built (web/dist)")
    if system.find("npm") is None:
        return WINDOW.result(
            False,
            "not built, and Node.js is not installed",
            "install Node.js (`brew install node`), then run `vision setup`",
        )
    return WINDOW.result(
        False,
        "not built; Node.js is installed",
        "`vision setup` builds it, or `cd web && npm ci && npm run build`",
    )


def app(config: Config, system: System) -> Check:
    name = macapp.app_name(config)
    if system.app_installed(config):
        return APP.result(True, f"installed in ~/Applications/{name}.app")
    if system.app_built(config):
        return APP.result(
            False, f"built (dist/{name}.app), not installed", "`vision app install`"
        )
    if system.swiftc() is None:
        return APP.result(
            False,
            "not built, and the Swift compiler is missing",
            "install Xcode or the Command Line Tools (`xcode-select --install`), "
            "then `vision app build`",
        )
    return APP.result(
        False, "not built", "`vision app build`, then `vision app install` (or `vision setup`)"
    )


APP_LOGIN = {
    "enabled": "the app opens at login, hidden, and starts the assistant",
    "requires-approval": "the app asked to open at login; approve it in System Settings, "
    "General, Login Items",
    "off": "the app is installed but does not open at login",
}


def start_at_login(config: Config, system: System) -> Check:
    if not (system.agent_installed() and system.agent_loaded()) and system.app_installed(config):
        state = system.app_login_item(config)
        if state is None:
            return LOGIN.result(
                False, "the app is installed, but it could not say", "reinstall: `vision app install`"
            )
        return LOGIN.result(
            state == "enabled",
            APP_LOGIN[state],
            "turn on Start at login in the app's menu bar item (or `vision setup`)",
        )
    installed = system.agent_installed()
    loaded = installed and system.agent_loaded()
    if loaded:
        detail = "installed and loaded"
    else:
        detail = "installed but not loaded" if installed else "not installed"
    return LOGIN.result(loaded, detail, "`vision install` (or `vision setup`)")


def house(config: Config, system: System) -> Check:
    path = config.paths.house_file
    try:
        user = store.read_toml(path) if path.is_file() else {}
        layout = build_layout(store.read_toml(store.DEFAULT_FILE), user, config)
    except HouseError as exc:
        return HOUSE.result(False, str(exc), f"fix {path}")
    projects = sum(1 for r in layout.rooms if r.folders)
    name = layout.agents[HOST].name if HOST in layout.agents else config.assistant.name
    return HOUSE.result(
        True,
        f"assistant {name}, {projects} of {len(layout.rooms)} rooms with project folders, "
        f"monthly cap ${config.budget.monthly_cap_usd:,.0f}",
    )


def tailscale(config: Config, system: System) -> Check:
    found = system.find("tailscale") is not None
    return TAILSCALE.result(
        found,
        "installed" if found else "not installed",
        "install it from tailscale.com when you want remote access",
    )


ORDER: tuple[Callable[[Config, System], Check], ...] = (
    python,
    extras,
    local_model,
    speech_models,
    microphone,
    github,
    window,
    app,
    start_at_login,
    house,
    tailscale,
)


def run_checks(config: Config, system: System, *, online: bool = False) -> list[Check]:
    """Every check, in order. Only `online` reaches the network (one unbilled API call)."""
    return [api_key(config, system, online=online), *(check(config, system) for check in ORDER)]
