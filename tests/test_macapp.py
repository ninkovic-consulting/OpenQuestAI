"""`vision app`: the Info.plist, the paths, and the build, with the compiler faked."""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from vision import __version__, display_version, macapp
from vision.core import cli
from vision.core.config import Config, load_config
from vision.macapp import bundle, installation


class FakeRun:
    """Stands in for `subprocess.run`: answers `xcrun` and records the build script's call."""

    def __init__(self, swiftc: Path | None, build_status: int = 0) -> None:
        self.swiftc = swiftc
        self.build_status = build_status
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self.plists: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if argv[:2] == ["xcrun", "--find"]:
            found = self.swiftc is not None
            return subprocess.CompletedProcess(argv, 0 if found else 1, str(self.swiftc or ""), "")
        self.envs.append(kwargs.get("env", {}))
        self.plists.append(plistlib.loads(Path(argv[3]).read_bytes()))
        if self.build_status == 0:
            (Path(argv[2]) / "Contents" / "MacOS").mkdir(parents=True)
        return subprocess.CompletedProcess(argv, self.build_status, "", "")


@pytest.fixture(autouse=True)
def no_build_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """A build made by hand has no run number, whatever the environment says."""
    monkeypatch.delenv(bundle.BUILD_NUMBER_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").touch()
    return root


@pytest.fixture
def swiftc(tmp_path: Path) -> Path:
    path = tmp_path / "Xcode" / "swiftc"
    path.parent.mkdir()
    path.touch()
    return path


def named(config: Config, name: str) -> Config:
    path = config.paths.config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[assistant]\nname = "{name}"\n[server]\nport = 7400\n')
    return load_config(config.paths.home)


def test_info_plist(config: Config, project: Path) -> None:
    info = plistlib.loads(bundle.info_plist(config, project=project))
    assert info["CFBundleIdentifier"] == "org.openquestai.vision"
    assert info["CFBundleName"] == info["CFBundleDisplayName"] == "Vision"
    assert info["CFBundleExecutable"] == "Vision"
    assert info["CFBundleShortVersionString"] == display_version()
    assert info["CFBundleVersion"] == "0"
    assert info["CFBundleIconFile"] == "AppIcon"
    assert info["LSMinimumSystemVersion"] == bundle.MIN_MACOS
    assert info["VisionProjectPath"] == str(project)
    assert info["VisionHome"] == str(config.paths.home)
    assert info["VisionPort"] == 7341
    assert info["NSMicrophoneUsageDescription"].startswith("Vision listens")
    exceptions = info["NSAppTransportSecurity"]["NSExceptionDomains"]
    assert exceptions == {"127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True}}
    assert "NSAllowsArbitraryLoads" not in info["NSAppTransportSecurity"]


@pytest.mark.parametrize(
    ("version", "shown"),
    [
        ("0.1.0b1", "0.1.0-beta"),
        ("0.1.0b2", "0.1.0-beta.2"),
        ("0.2.0a1", "0.2.0-alpha"),
        ("1.0.0rc1", "1.0.0-rc"),
        ("0.1.0", "0.1.0"),
        ("1.2.3.dev4", "1.2.3.dev4"),
    ],
)
def test_the_version_people_read(version: str, shown: str) -> None:
    assert display_version(version) == shown


def test_the_version_is_a_valid_python_version() -> None:
    from packaging.version import Version

    assert str(Version(__version__)) == __version__  # already in PEP 440's own spelling
    assert Version(__version__).is_prerelease == (display_version() != __version__)


def test_info_plist_carries_the_build_number(config: Config, project: Path) -> None:
    by_hand = plistlib.loads(bundle.info_plist(config, project=project))
    piped = plistlib.loads(bundle.info_plist(config, project=project, number="57"))
    assert by_hand["CFBundleVersion"] == "0"
    assert piped["CFBundleVersion"] == "57"
    assert piped["CFBundleShortVersionString"] == by_hand["CFBundleShortVersionString"]


def test_the_build_number_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert bundle.build_number({}) == "0"
    assert bundle.build_number({bundle.BUILD_NUMBER_ENV: " 0042 "}) == "42"
    monkeypatch.setenv(bundle.BUILD_NUMBER_ENV, "9")
    assert bundle.build_number() == "9"
    for bad in ("v9", "1.2", "-3", "٣"):
        with pytest.raises(macapp.AppBuildError, match=bundle.BUILD_NUMBER_ENV):
            bundle.build_number({bundle.BUILD_NUMBER_ENV: bad})


def test_info_plist_takes_the_name_and_port(config: Config, project: Path) -> None:
    config = named(config, "Ada & <Bo>/2")
    info = plistlib.loads(bundle.info_plist(config, project=project, icon=False))
    assert info["CFBundleDisplayName"] == "Ada & <Bo>/2"
    assert info["CFBundleExecutable"] == "Ada & <Bo>-2"
    assert info["NSMicrophoneUsageDescription"].startswith("Ada & <Bo>/2 listens")
    assert info["VisionPort"] == 7400
    assert "CFBundleIconFile" not in info


def test_paths(config: Config, tmp_path: Path) -> None:
    assert bundle.built_app(config, tmp_path) == tmp_path / "Vision.app"
    assert installation.installed_app(config, tmp_path / "Apps") == tmp_path / "Apps" / "Vision.app"
    assert installation.executable(config, tmp_path / "Vision.app") == (
        tmp_path / "Vision.app" / "Contents" / "MacOS" / "Vision"
    )
    assert bundle.app_name(named(config, " ..")) == "Vision"


def test_build_calls_the_script(
    config: Config, project: Path, swiftc: Path, tmp_path: Path
) -> None:
    icon = tmp_path / "Vision.icns"
    icon.write_bytes(b"icns")
    run = FakeRun(swiftc)
    dist = tmp_path / "dist"
    app = bundle.build(config, project=project, dist=dist, icon=icon, run=run)

    assert app == dist / "Vision.app"
    script = run.calls[1]
    assert script[:3] == ["/bin/sh", str(bundle.BUILD_SCRIPT), str(app)]
    assert script[4:] == ["Vision", bundle.BUNDLE_ID, bundle.MIN_MACOS, str(icon)]
    assert run.envs[0]["SWIFTC"] == str(swiftc)
    assert run.plists[0]["VisionProjectPath"] == str(project)
    assert not (dist / "Info.plist").exists()  # the rendered plist is not left behind


def test_build_without_an_icon(config: Config, project: Path, swiftc: Path, tmp_path: Path) -> None:
    run = FakeRun(swiftc)
    bundle.build(config, project=project, dist=tmp_path, icon=tmp_path / "none.icns", run=run)
    assert len(run.calls[1]) == 7
    assert "CFBundleIconFile" not in run.plists[0]


def test_build_needs_the_compiler(config: Config, project: Path, tmp_path: Path) -> None:
    run = FakeRun(None)
    with pytest.raises(macapp.AppBuildError, match=r"swiftc.*xcode-select --install"):
        bundle.build(config, project=project, dist=tmp_path, run=run)
    assert run.calls == [["xcrun", "--find", "swiftc"]]


def test_build_needs_the_venv(config: Config, swiftc: Path, tmp_path: Path) -> None:
    with pytest.raises(macapp.AppBuildError, match="uv sync"):
        bundle.build(config, project=tmp_path, dist=tmp_path, run=FakeRun(swiftc))


def test_build_failure_is_reported(
    config: Config, project: Path, swiftc: Path, tmp_path: Path
) -> None:
    with pytest.raises(macapp.AppBuildError, match="exit status 1"):
        bundle.build(config, project=project, dist=tmp_path, run=FakeRun(swiftc, build_status=1))


def test_install_replaces_the_old_copy(config: Config, tmp_path: Path) -> None:
    dist, apps = tmp_path / "dist", tmp_path / "Apps"
    with pytest.raises(FileNotFoundError, match="vision app build"):
        installation.install(config, dist=dist, applications=apps)
    (dist / "Vision.app" / "Contents").mkdir(parents=True)
    (dist / "Vision.app" / "Contents" / "new").touch()
    (apps / "Vision.app" / "Contents").mkdir(parents=True)
    (apps / "Vision.app" / "Contents" / "old").touch()
    target = installation.install(config, dist=dist, applications=apps)
    assert sorted(p.name for p in (target / "Contents").iterdir()) == ["new"]


def test_app_to_open_prefers_the_installed_one(config: Config, tmp_path: Path) -> None:
    dist, apps = tmp_path / "dist", tmp_path / "Apps"
    with pytest.raises(FileNotFoundError):
        installation.app_to_open(config, dist=dist, applications=apps)
    (dist / "Vision.app").mkdir(parents=True)
    assert installation.app_to_open(config, dist=dist, applications=apps) == dist / "Vision.app"
    (apps / "Vision.app").mkdir(parents=True)
    assert installation.app_to_open(config, dist=dist, applications=apps) == apps / "Vision.app"


def test_login_item_asks_the_app(config: Config, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def answer(out: str, code: int = 0, err: str = "") -> bundle.Runner:
        def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            seen.append(argv)
            return subprocess.CompletedProcess(argv, code, out, err)

        return run

    app = tmp_path / "Vision.app"
    assert installation.login_item(config, app, "status", answer("requires-approval\n")) == (
        "requires-approval"
    )
    assert seen[0] == [str(app / "Contents" / "MacOS" / "Vision"), "--login-item", "status"]
    with pytest.raises(RuntimeError, match="denied"):
        installation.login_item(config, app, "on", answer("", 1, "denied"))
    with pytest.raises(RuntimeError, match="maybe"):
        installation.login_item(config, app, "status", answer("maybe"))


def test_cli_reports_a_missing_compiler(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bundle, "find_swiftc", lambda run=None: None)
    assert cli.main(["app", "build"]) == 1
    assert "Swift compiler (swiftc) was not found" in capsys.readouterr().out


def test_cli_build_into_another_folder(
    config: Config, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--out` builds a test copy elsewhere, leaving `dist/` (and the app running from it) alone."""
    seen: list[dict[str, Any]] = []

    def fake_build(config: Config, **kwargs: Any) -> Path:
        seen.append(kwargs)
        return kwargs.get("dist", Path("/fake/dist")) / "Vision.app"

    monkeypatch.setattr(macapp, "build", fake_build)
    assert cli.main(["app", "build", "--out", str(tmp_path / "scratch")]) == 0
    assert seen == [{"dist": tmp_path / "scratch"}]
    assert f"Built {tmp_path / 'scratch' / 'Vision.app'}" in capsys.readouterr().out
    assert cli.main(["app", "build"]) == 0
    assert seen[-1] == {}
