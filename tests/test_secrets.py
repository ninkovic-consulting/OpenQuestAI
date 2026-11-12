from pathlib import Path

import pytest
from keyring.errors import NoKeyringError

from vision.core import secrets


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.env"
    monkeypatch.setenv("VISION_ENV_FILE", str(path))
    return path


def set_keychain(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr("keyring.get_password", lambda service, account: value)


def test_nothing_anywhere(env_file: Path) -> None:
    assert secrets.get_api_key() is None
    assert secrets.api_key_source() is None


def test_keychain_wins(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    set_keychain(monkeypatch, "from-keychain")
    assert secrets.get_api_key() == "from-keychain"
    assert secrets.api_key_source() == "keychain"


def test_env_file_beats_environment(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file.write_text('# comment\nOTHER=1\nexport ANTHROPIC_API_KEY="from-file"\n')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert secrets.get_api_key() == "from-file"
    assert secrets.api_key_source() == "env_file"


def test_environment_last(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file.write_text("ANTHROPIC_API_KEY=\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert secrets.get_api_key() == "from-env"
    assert secrets.api_key_source() == "environment"


def test_unquoted_value_with_comment(env_file: Path) -> None:
    env_file.write_text("ANTHROPIC_API_KEY=abc123 # note\n")
    assert secrets.get_api_key() == "abc123"


def test_keyring_failure_falls_through(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(service: str, account: str) -> str:
        raise NoKeyringError("no backend")

    monkeypatch.setattr("keyring.get_password", broken)
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n")
    assert secrets.get_api_key() == "from-file"


def test_default_env_file_is_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISION_ENV_FILE")
    assert secrets.env_file_path() == Path(__file__).resolve().parents[1] / ".env"


def test_store_uses_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "keyring.set_password", lambda s, a, v: stored.__setitem__((s, a), v)
    )
    secrets.store_api_key("k")
    assert stored == {("vision", "anthropic_api_key"): "k"}
