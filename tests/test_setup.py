"""`vision doctor` and `vision setup`, with the outside world faked.

No network, no real `gh`, no Keychain, no microphone, no LaunchAgent: every
outside call goes through `FakeSystem`.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from vision.core import cli
from vision.core.config import Config, load_config
from vision.setup import checks, doctor, run_checks
from vision.macapp import LoginState
from vision.memory import profile
from vision.setup.system import KeyVerdict
from vision.setup.wizard import TOOLS_NOTE, run_setup
from vision.voice.settings import VoiceSettings

ORDER = [
    "api_key",
    "python",
    "extras",
    "local_model",
    "speech_models",
    "microphone",
    "github",
    "window",
    "app",
    "login",
    "house",
    "tailscale",
]
LOCAL_REPO = "mlx-community/Qwen3-4B-Instruct-2507-4bit"


@dataclass
class FakeSystem:
    programs: set[str] = field(default_factory=lambda: {"uv", "gh", "npm", "tailscale"})
    exit_codes: dict[tuple[str, ...], int] = field(default_factory=dict)
    modules: set[str] = field(
        default_factory=lambda: {"mlx_lm", "mlx_audio", "sounddevice", "webview"}
    )
    cache: dict[str, int] = field(default_factory=dict)
    version: str = "3.12.11"
    key_source: str | None = "keychain"
    verdict: KeyVerdict = "accepted"
    installed: bool = True
    loaded: bool = True
    built: bool = True
    has_swiftc: bool = True
    app_is_built: bool = True
    app_is_installed: bool = False
    login_item: LoginState | None = "off"
    # what the setup did
    calls: list[str] = field(default_factory=list)
    stored: list[str] = field(default_factory=list)
    ran: list[tuple[str, ...]] = field(default_factory=list)

    def find(self, name: str) -> Path | None:
        return Path("/fake/bin") / name if name in self.programs else None

    def exit_code(self, argv: list[str]) -> int | None:
        self.ran.append(tuple(argv))
        return self.exit_codes.get(tuple(argv), 0) if argv[0] in self.programs else None

    def output(self, argv: list[str]) -> str | None:
        self.ran.append(tuple(argv))
        if argv == ["uv", "--version"] and "uv" in self.programs:
            return "uv 0.12.0 (Homebrew 2026-07-28 aarch64-apple-darwin)"
        return None

    def has_module(self, name: str) -> bool:
        return name in self.modules

    def cached_size(self, repo: str, needs: str = "*") -> int | None:
        return self.cache.get(repo)

    def python_version(self) -> str:
        return self.version

    def api_key_source(self) -> str | None:
        return self.key_source

    def verify_key(self) -> KeyVerdict:
        self.calls.append("verify_key")
        return self.verdict

    def agent_installed(self) -> bool:
        return self.installed

    def agent_loaded(self) -> bool:
        return self.loaded

    def window_built(self) -> bool:
        return self.built

    def swiftc(self) -> Path | None:
        return Path("/fake/xcode/swiftc") if self.has_swiftc else None

    def app_built(self, config: Config) -> bool:
        return self.app_is_built

    def app_installed(self, config: Config) -> bool:
        return self.app_is_installed

    def app_login_item(self, config: Config) -> LoginState | None:
        return self.login_item if self.app_is_installed else None

    def store_key(self, key: str) -> None:
        self.stored.append(key)
        self.key_source = "keychain"

    def download_size(self, repos: list[str]) -> int | None:
        return 2_300_000_000 * len(repos)

    def download(self, repos: list[str]) -> None:
        self.calls.append(f"download {' '.join(repos)}")
        for repo in repos:
            self.cache[repo] = 1

    def download_local_model(self, config: Config) -> None:
        self.calls.append("download_local_model")
        self.cache[config.brain.local_model] = 2_300_000_000

    def mic_check(self) -> None:
        self.calls.append("mic_check")

    def build_window(self) -> bool:
        self.calls.append("build_window")
        self.built = True
        return True

    def install_agent(self, config: Config) -> Path:
        self.calls.append("install_agent")
        self.installed = self.loaded = True
        return Path("/fake/LaunchAgents/agent.plist")

    def build_app(self, config: Config) -> Path:
        self.calls.append("build_app")
        self.app_is_built = True
        return Path("/fake/dist/Vision.app")

    def install_app(self, config: Config) -> Path:
        self.calls.append("install_app")
        self.app_is_installed = True
        return Path("/fake/Applications/Vision.app")

    def set_app_login_item(self, config: Config, on: bool) -> LoginState:
        self.calls.append(f"app_login {'on' if on else 'off'}")
        self.login_item = "enabled" if on else "off"
        return "enabled" if on else "off"


def speech_repos(config: Config) -> tuple[str, ...]:
    return VoiceSettings.from_config(config).model_repos()


def everything(config: Config) -> FakeSystem:
    """A Mac where everything is in place."""
    cache = {LOCAL_REPO: 2_300_000_000, **{r: 500_000_000 for r in speech_repos(config)}}
    return FakeSystem(cache=cache, app_is_installed=True)


def by_id(found: list[checks.Check]) -> dict[str, checks.Check]:
    return {c.id: c for c in found}


# ------------------------------------------------------------ each check


def test_all_in_place(config: Config) -> None:
    found = run_checks(config, everything(config))
    assert [c.id for c in found] == ORDER
    assert {c.id: c.status for c in found} == {
        **{i: "ok" for i in ORDER},
        "microphone": "optional",
    }
    assert [c.id for c in found if c.needed] == ["api_key", "python", "house"]
    assert all(c.fix == "" for c in found if c.status == "ok")


def test_api_key_missing_and_where_it_is(config: Config) -> None:
    system = FakeSystem(key_source=None)
    check = checks.api_key(config, system)
    assert (check.status, check.needed) == ("missing", True)
    assert "vision setup" in check.fix
    for source, words in [("keychain", "Keychain"), ("env_file", ".env"), ("environment", "ANTHRO")]:
        check = checks.api_key(config, FakeSystem(key_source=source))
        assert check.status == "ok" and words in check.detail


def test_api_key_is_verified_only_online(config: Config) -> None:
    system = FakeSystem()
    checks.api_key(config, system)
    run_checks(config, system)
    assert system.calls == []
    for verdict, status, words in [
        ("accepted", "ok", "accepted"),
        ("refused", "missing", "refused"),
        ("unreachable", "ok", "could not be reached"),
    ]:
        system = FakeSystem(verdict=verdict)
        check = checks.api_key(config, system, online=True)
        assert system.calls == ["verify_key"]
        assert check.status == status and words in check.detail


def test_python_inside_the_app(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VISION_RESOURCES", str(tmp_path))
    system = FakeSystem(programs=set())
    check = checks.python(config, system)
    assert check.status == "ok" and check.detail == "Python 3.12.11, inside the app"
    assert system.ran == []


def test_python_and_uv(config: Config) -> None:
    ok = checks.python(config, FakeSystem())
    assert ok.status == "ok" and ok.detail == "uv 0.12.0, Python 3.12.11"
    assert checks.python(config, FakeSystem(programs=set())).status == "missing"
    assert checks.python(config, FakeSystem(version="3.11.9")).status == "missing"


def test_optional_parts(config: Config) -> None:
    check = checks.extras(config, FakeSystem(modules={"mlx_lm", "webview"}))
    assert check.status == "optional"
    assert check.detail == "installed: local, ui; not installed: voice"
    assert check.fix == "`uv sync --all-extras`"


def test_local_model(config: Config) -> None:
    got = checks.local_model(config, FakeSystem(cache={LOCAL_REPO: 2_300_000_000}))
    assert got.status == "ok" and got.detail.endswith("downloaded, 2.3 GB")
    lacking = checks.local_model(config, FakeSystem())
    assert lacking.status == "optional" and "not downloaded" in lacking.detail
    served = config.model_copy(
        update={"brain": config.brain.model_copy(update={"local_backend": "openai"})}
    )
    assert checks.local_model(served, FakeSystem()).status == "ok"


def test_speech_models(config: Config) -> None:
    repos = speech_repos(config)
    some = checks.speech_models(config, FakeSystem(cache={repos[0]: 1_500_000_000}))
    assert some.status == "optional"
    assert some.detail.startswith(f"1 of {len(repos)} downloaded; missing ")
    assert "about 2 GB" in some.fix
    full = checks.speech_models(config, FakeSystem(cache={r: 500_000_000 for r in repos}))
    assert full.status == "ok" and full.detail == f"all {len(repos)} downloaded, 2.0 GB"


def test_microphone_is_never_probed(config: Config) -> None:
    system = FakeSystem()
    check = checks.microphone(config, system)
    assert check.status == "optional" and "not checked" in check.detail
    assert "vision.voice.check" in check.fix
    assert system.ran == [] and system.calls == []


def test_github(config: Config) -> None:
    absent = checks.github(config, FakeSystem(programs=set()))
    assert absent.status == "optional" and "not installed" in absent.detail
    system = FakeSystem(exit_codes={("gh", "auth", "status"): 1})
    out = checks.github(config, system)
    assert out.detail == "installed, not signed in" and out.fix == "`gh auth login`"
    assert system.ran == [("gh", "auth", "status")]
    assert checks.github(config, FakeSystem()).status == "ok"


def test_window(config: Config) -> None:
    assert checks.window(config, FakeSystem()).status == "ok"
    with_node = checks.window(config, FakeSystem(built=False))
    assert "Node.js is installed" in with_node.detail and "npm run build" in with_node.fix
    no_node = checks.window(config, FakeSystem(built=False, programs=set()))
    assert "Node.js is not installed" in no_node.detail


def test_start_at_login(config: Config) -> None:
    assert checks.start_at_login(config, FakeSystem()).detail == "installed and loaded"
    half = checks.start_at_login(config, FakeSystem(loaded=False))
    assert half.status == "optional" and half.detail == "installed but not loaded"
    assert checks.start_at_login(config, FakeSystem(installed=False)).detail == "not installed"


def test_start_at_login_through_the_app(config: Config) -> None:
    def app(state: LoginState | None) -> FakeSystem:
        return FakeSystem(installed=False, loaded=False, app_is_installed=True, login_item=state)

    on = checks.start_at_login(config, app("enabled"))
    assert on.status == "ok" and "opens at login" in on.detail
    waiting = checks.start_at_login(config, app("requires-approval"))
    assert waiting.status == "optional" and "Login Items" in waiting.detail
    off = checks.start_at_login(config, app("off"))
    assert off.status == "optional" and "menu bar item" in off.fix
    assert "could not say" in checks.start_at_login(config, app(None)).detail
    # A loaded daemon LaunchAgent is enough, app or not.
    agent = FakeSystem(app_is_installed=True, login_item="off")
    assert checks.start_at_login(config, agent).detail == "installed and loaded"


def test_mac_app(config: Config) -> None:
    assert checks.app(config, FakeSystem(app_is_installed=True)).detail == (
        "installed in ~/Applications/Vision.app"
    )
    built = checks.app(config, FakeSystem())
    assert built.status == "optional" and built.fix == "`vision app install`"
    unbuilt = checks.app(config, FakeSystem(app_is_built=False))
    assert unbuilt.detail == "not built" and "vision app build" in unbuilt.fix
    no_compiler = checks.app(config, FakeSystem(app_is_built=False, has_swiftc=False))
    assert "Swift compiler is missing" in no_compiler.detail
    assert "xcode-select --install" in no_compiler.fix


def test_house(config: Config) -> None:
    check = checks.house(config, FakeSystem())
    assert check.detail == "assistant Vision, 0 of 10 rooms with project folders, monthly cap $150"
    assert not config.paths.house_file.exists()  # read without creating
    config.paths.house_file.parent.mkdir(parents=True, exist_ok=True)
    config.paths.house_file.write_text('[[rooms]]\nid = "garage"\nfolders = ["~/p", "~/q"]\n')
    assert "1 of 10 rooms" in checks.house(config, FakeSystem()).detail
    config.paths.house_file.write_text('[[rooms]]\nid = "garage"\nproject = "~/p"\n')
    old = checks.house(config, FakeSystem())
    assert old.status == "missing" and "looks like a folder path" in old.detail and "put folders in folders" in old.detail
    config.paths.house_file.write_text('[[rooms]]\nid = "garage"\ntools = ["anvil"]\n')
    broken = checks.house(config, FakeSystem())
    assert broken.status == "missing" and "anvil" in broken.detail


def test_tailscale(config: Config) -> None:
    assert checks.tailscale(config, FakeSystem()).status == "ok"
    assert checks.tailscale(config, FakeSystem(programs=set())).status == "optional"


# ------------------------------------------------------------ doctor output


def test_json_shape_and_exit_codes(config: Config) -> None:
    good = run_checks(config, everything(config))
    body = json.loads(doctor.as_json(good))
    assert body["ok"] is True and doctor.exit_code(good) == 0
    assert [c["id"] for c in body["checks"]] == ORDER
    assert set(body["checks"][0]) == {
        "id", "title", "needed_for", "needed", "status", "detail", "fix"
    }
    bad = run_checks(config, FakeSystem(key_source=None))
    assert json.loads(doctor.as_json(bad))["ok"] is False and doctor.exit_code(bad) == 1


def test_optional_gaps_do_not_fail(config: Config) -> None:
    found = run_checks(config, FakeSystem(programs={"uv"}, modules=set(), built=False))
    assert doctor.exit_code(found) == 0


def test_text_groups_needed_first(config: Config) -> None:
    text = doctor.as_text(run_checks(config, FakeSystem(key_source=None)), "Vision")
    assert text.index("Needed") < text.index("Anthropic API key") < text.index("Optional")
    assert "MISSING" in text and "fix: run `vision setup`" in text
    assert text.endswith("Something needed is missing; see MISSING above.")


def test_cli_doctor(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("vision.setup.MacSystem", lambda: everything(config))
    assert cli.main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    monkeypatch.setattr("vision.setup.MacSystem", lambda: FakeSystem(key_source=None))
    assert cli.main(["doctor"]) == 1
    assert "Everything needed" not in capsys.readouterr().out


# ------------------------------------------------------------ setup, scripted


class Script:
    def __init__(self, answers: list[str], secrets: list[str] | None = None) -> None:
        self.answers = list(answers)
        self.secrets = list(secrets or [])
        self.prompts: list[str] = []
        self.out: list[str] = []

    def say(self, text: str = "") -> None:
        self.out.append(text)

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def secret(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.secrets.pop(0)

    @property
    def text(self) -> str:
        return "\n".join(self.out)


def project(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:a/b.git\n')
    (root / "package.json").write_text("{}")
    return root


def test_setup_walks_through_and_fixes(config: Config, tmp_path: Path) -> None:
    system = FakeSystem(key_source=None, installed=False, loaded=False, built=False)
    folder = project(tmp_path)
    io = Script(
        answers=[
            "",  # store a key? default yes
            "y",  # check it
            "y",  # download the local model
            "n",  # speech models
            "n",  # microphone
            "y",  # build the window
            "y",  # install the app
            "n",  # open the app at login
            "Ada",  # name
            "lots",  # cap, refused
            "40",  # cap
            "Sam",  # what to call you
            "A two-person bakery in Graz.",  # the business
            "",  # anything else: left empty
            "y",  # attach a project
            "workshop",
            str(folder),
            "n",  # not all tools
            "y",  # Git
            "n",  # GitHub
            "",  # npm, default yes
            "",  # finish
        ],
        secrets=["sk-test-not-real"],
    )
    code = run_setup(config, system, io)

    assert code == 0
    assert system.stored == ["sk-test-not-real"]
    assert system.calls == ["verify_key", "download_local_model", "build_window", "install_app"]
    assert "sk-test-not-real" not in io.text
    assert "The API accepted the key." in io.text
    assert "Download: 2.3 GB" in io.text
    assert "A cap is a number of dollars" in io.text

    saved = tomllib.loads(config.paths.config_file.read_text())
    assert saved == {
        "assistant": {"name": "Ada", "setup_completed": True},
        "budget": {"monthly_cap_usd": 40.0},
    }
    house = tomllib.loads(config.paths.house_file.read_text())
    workshop = next(r for r in house["rooms"] if r["id"] == "workshop")
    assert workshop["folders"] == [str(folder.resolve())]
    assert workshop["tools"] == ["git", "npm"]
    assert "Proposed tools: Git" in io.text
    assert TOOLS_NOTE.format(name="Ada") in io.text
    assert "OpenQuestAI doctor, for Ada" in io.text
    assert "monthly cap $40" in io.text
    assert profile.read(config.paths.house) == profile.Profile("Sam", "A two-person bakery in Graz.", "")
    assert any(p.startswith("What should I call you?") for p in io.prompts)


def test_setup_twice_changes_nothing(config: Config) -> None:
    system = everything(config)
    io = Script(answers=[])  # input ended: every question takes its default
    assert run_setup(config, system, io) == 0
    assert system.calls == [] and system.stored == []
    written = config.paths.config_file.read_bytes()
    assert tomllib.loads(written.decode()) == {"assistant": {"setup_completed": True}}
    assert run_setup(load_config(config.paths.home), system, Script(answers=[])) == 0
    assert config.paths.config_file.read_bytes() == written
    assert "Done: Vision starts at login." in io.text
    assert "Done: all speech models are downloaded." in io.text
    assert "Everything needed is in place." in io.text


def test_setup_skips_without_the_optional_parts(config: Config) -> None:
    system = FakeSystem(
        modules=set(), built=False, programs={"uv"}, installed=False,
        has_swiftc=False, app_is_built=False,
    )
    io = Script(answers=["n"] * 3)
    run_setup(config, system, io)
    assert system.calls == []
    assert "needs `uv sync --extra local`" in io.text
    assert "Not built. Install Node.js" in io.text
    assert "Not built. Install Xcode" in io.text


def test_setup_builds_the_app_and_opens_it_at_login(config: Config) -> None:
    system = FakeSystem(installed=False, loaded=False, app_is_built=False)
    # key, check, local model, speech, mic; then build, install, login
    io = Script(answers=["n"] * 5 + ["", "", "y"])
    run_setup(config, system, io)
    assert system.calls == ["build_app", "install_app", "app_login on"]
    assert "The app opens at login, hidden, and starts the assistant." in io.text
    assert "~/Library/LaunchAgents" not in io.text


def test_setup_says_when_the_app_awaits_approval(config: Config) -> None:
    system = FakeSystem(
        installed=False, loaded=False, app_is_installed=True, login_item="requires-approval"
    )
    run_setup(config, system, io := Script(answers=[]))
    assert system.calls == []
    assert "Approve it in System Settings" in io.text


def test_setup_can_be_stopped(config: Config) -> None:
    class Interrupt(Script):
        def ask(self, prompt: str) -> str:
            raise KeyboardInterrupt

    io = Interrupt(answers=[])
    assert run_setup(config, FakeSystem(), io) == 130
    assert "Stopped." in io.text


def test_doctor_reads_the_saved_settings(config: Config) -> None:
    run_setup(config, everything(config), Script(answers=["n", "n", "n", "Bo", "12"]))
    again = load_config(config.paths.home)
    assert (again.assistant.name, again.budget.monthly_cap_usd) == ("Bo", 12.0)
