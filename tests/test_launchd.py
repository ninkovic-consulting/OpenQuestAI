import plistlib
import sys

import pytest

from vision.core import cli, launchd
from vision.core.config import Config


def test_plist_contents(config: Config) -> None:
    plist = plistlib.loads(launchd.plist_bytes(config, port=7400))
    assert plist["Label"] == launchd.LABEL
    assert plist["ProgramArguments"] == [sys.executable, "-m", "vision", "run", "--port", "7400"]
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True
    assert plist["StandardOutPath"] == str(config.paths.logs / "daemon.out.log")
    assert plist["StandardErrorPath"] == str(config.paths.logs / "daemon.err.log")
    assert plist["EnvironmentVariables"]["VISION_HOME"] == str(config.paths.home)


def test_install_dry_run_only_prints(
    config: Config, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("dry run must not touch launchd")

    monkeypatch.setattr(launchd, "install", forbidden)
    monkeypatch.setattr(launchd.subprocess, "run", forbidden)
    assert cli.main(["install", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "<key>KeepAlive</key>" in out and launchd.LABEL in out
