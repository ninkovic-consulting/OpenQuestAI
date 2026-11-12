"""The parts of the real system adapter that only read the disk: the download cache and programs."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from vision.core.programs import find_program, search_dirs
from vision.setup import hf_cache


def fake_repo(cache: Path, repo: str, files: dict[str, int]) -> None:
    """A cache entry laid out like huggingface_hub's: snapshot symlinks into blobs."""
    base = cache / f"models--{repo.replace('/', '--')}"
    snapshot = base / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (base / "blobs").mkdir()
    for i, (name, size) in enumerate(files.items()):
        blob = base / "blobs" / f"blob{i}"
        blob.write_bytes(b"x" * size)
        (snapshot / name).symlink_to(blob)


def test_cached_size_follows_snapshot_links(tmp_path: Path) -> None:
    fake_repo(tmp_path, "org/model", {"config.json": 10, "model.safetensors": 1000})
    assert hf_cache.cached_size("org/model", cache=tmp_path) == 1010
    assert hf_cache.cached_size("org/model", needs="*.safetensors", cache=tmp_path) == 1010
    assert hf_cache.cached_size("org/other", cache=tmp_path) is None


def test_cached_size_needs_the_weights(tmp_path: Path) -> None:
    fake_repo(tmp_path, "org/half", {"config.json": 10})
    assert hf_cache.cached_size("org/half", needs="*.safetensors", cache=tmp_path) is None


def test_hub_cache_follows_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("HF_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert hf_cache.hub_cache() == tmp_path / ".cache" / "huggingface" / "hub"
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert hf_cache.hub_cache() == tmp_path / "hf" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    assert hf_cache.hub_cache() == tmp_path / "hub"


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_programs_are_found_outside_a_short_path(tmp_path: Path) -> None:
    old = executable(tmp_path / ".nvm" / "versions" / "node" / "v9.1.0" / "bin" / "visiontool")
    new = executable(tmp_path / ".nvm" / "versions" / "node" / "v24.2.0" / "bin" / "visiontool")
    assert find_program("visiontool", path="/usr/bin", home=tmp_path) == new
    assert old != new
    local = executable(tmp_path / ".local" / "bin" / "othertool")
    assert find_program("othertool", path="", home=tmp_path) == local
    assert find_program("no-such-tool-anywhere", path="", home=tmp_path) is None


def test_path_wins(tmp_path: Path) -> None:
    first = executable(tmp_path / "first" / "visiontool")
    executable(tmp_path / ".local" / "bin" / "visiontool")
    assert find_program("visiontool", path=str(first.parent), home=tmp_path) == first


def test_search_dirs_include_homebrew(tmp_path: Path) -> None:
    dirs = search_dirs(tmp_path)
    assert Path("/opt/homebrew/bin") in dirs and Path("/usr/local/bin") in dirs
    assert all(os.path.isabs(d) for d in dirs)
