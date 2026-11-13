"""espeak-ng's data reached through a short path when its own is too long (the app's bundle)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from vision.voice.tts import ESPEAK_LINK, ESPEAK_MAX_PATH, espeak_data_path, use_espeak_data


def long_folder(root: Path) -> Path:
    """A folder whose path is longer than espeak-ng's buffer."""
    folder = root
    while len(str(folder)) < ESPEAK_MAX_PATH + 20:
        folder = folder / "a-rather-long-folder-name"
    folder.mkdir(parents=True)
    return folder


def test_a_short_path_is_used_as_it_is(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert espeak_data_path(str(tmp_path / "data"), home) == str(tmp_path / "data")
    assert not home.exists()


def test_a_long_path_is_reached_through_a_link_in_the_home(tmp_path: Path) -> None:
    real = long_folder(tmp_path / "bundle")
    (real / "phontab").write_text("data")
    home = tmp_path / "home"
    short = espeak_data_path(str(real), home)
    assert short == str(home / ESPEAK_LINK)
    assert len(short) < ESPEAK_MAX_PATH
    assert os.readlink(short) == str(real)
    assert (Path(short) / "phontab").read_text() == "data"
    assert home.stat().st_mode & 0o777 == 0o700
    assert espeak_data_path(str(real), home) == short  # kept as it is


def test_a_link_to_an_older_bundle_is_pointed_at_the_new_one(tmp_path: Path) -> None:
    old, new = long_folder(tmp_path / "old"), long_folder(tmp_path / "new")
    home = tmp_path / "home"
    espeak_data_path(str(old), home)
    assert espeak_data_path(str(new), home) == str(home / ESPEAK_LINK)
    assert os.readlink(home / ESPEAK_LINK) == str(new)
    assert sorted(p.name for p in home.iterdir()) == [ESPEAK_LINK]


def test_something_else_at_the_name_is_left_alone(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ESPEAK_LINK).mkdir(parents=True)
    assert espeak_data_path(str(long_folder(tmp_path / "bundle")), home) is None
    assert (home / ESPEAK_LINK).is_dir() and not (home / ESPEAK_LINK).is_symlink()


def test_no_short_path_in_a_long_home(tmp_path: Path) -> None:
    home = long_folder(tmp_path / "home")
    assert espeak_data_path(str(long_folder(tmp_path / "bundle")), home) is None


def test_a_made_up_name_gets_phonemes_from_a_bundle_with_a_long_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real espeak-ng, no sound: its data copied to a path too long for it, reached through the link."""
    loader = pytest.importorskip("espeakng_loader")
    espeak = pytest.importorskip("misaki.espeak")
    bundle = long_folder(tmp_path / "bundle") / "espeak-ng-data"
    shutil.copytree(loader.get_data_path(), bundle)
    assert len(str(bundle)) >= ESPEAK_MAX_PATH
    short = espeak_data_path(str(bundle), tmp_path / "home")
    assert short is not None
    monkeypatch.setattr(espeak.EspeakWrapper, "_ESPEAK_DATA_PATH", espeak.EspeakWrapper._ESPEAK_DATA_PATH)
    monkeypatch.delenv("PHONEMIZER_ESPEAK_DATA_PATH", raising=False)
    monkeypatch.setenv("ESPEAK_DATA_PATH", "")
    use_espeak_data(espeak.EspeakWrapper, short)
    fallback = espeak.EspeakFallback(british=False)
    assert fallback.backend._espeak.data_path == Path(short)  # espeak reads the short link itself
    phonemes, _ = fallback(type("Token", (), {"text": "Zorbelwick"})())
    assert phonemes  # spelt out, not skipped
