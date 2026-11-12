"""GET /api/fs/dirs: folder names only, inside the typed folder, never file contents."""

from __future__ import annotations

from pathlib import Path

import pytest
from settings_fakes import client, use

from vision.app import Daemon
from vision.settings.folders import BadPrefix, list_dirs


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "user"
    for name in ("Projects", "Pictures", "prototypes", "Music", ".config", ".private"):
        (home / name).mkdir(parents=True)
    (home / "Projects" / "vision").mkdir()
    (home / "Projects" / "notes.txt").write_text("secret")
    (home / "Program.txt").write_text("not a folder")
    (home / "Pro-link").symlink_to(home / "Projects")
    monkeypatch.setenv("HOME", str(home))
    return home


def names(prefix: str) -> list[str]:
    return [d["name"] for d in list_dirs(prefix)]


def test_lists_the_typed_folder_filtered_by_the_name(home: Path) -> None:
    assert list_dirs("~/Pr") == [
        {"name": "Projects", "path": "~/Projects"},
        {"name": "prototypes", "path": "~/prototypes"},
    ]
    assert names("~/") == ["Music", "Pictures", "Projects", "prototypes"]
    assert names("~") == names("~/")


def test_lists_inside_a_folder_after_the_slash(home: Path) -> None:
    assert list_dirs("~/Projects/") == [{"name": "vision", "path": "~/Projects/vision"}]


def test_absolute_paths_stay_absolute(home: Path) -> None:
    assert list_dirs(f"{home}/Mu") == [{"name": "Music", "path": f"{home}/Music"}]


def test_hidden_only_when_typed(home: Path) -> None:
    assert ".config" not in names("~/")
    assert names("~/.") == [".config", ".private"]
    assert names("~/.c") == [".config"]


def test_files_and_symlinks_are_left_out(home: Path) -> None:
    assert "Program.txt" not in names("~/Pro") and "Pro-link" not in names("~/Pro")
    assert "notes.txt" not in names("~/Projects/")


def test_missing_folder_is_empty(home: Path) -> None:
    assert list_dirs("~/Nowhere/") == []
    assert list_dirs("~/Program.txt/") == []


def test_at_most_fifty(tmp_path: Path) -> None:
    for i in range(60):
        (tmp_path / f"d{i:02}").mkdir()
    found = names(f"{tmp_path}/d")
    assert len(found) == 50 and found[0] == "d00"


@pytest.mark.parametrize("prefix", ["Projects", "./x", "", "~other/x", "~/../etc/", "/tmp/.."])
def test_refused_prefixes(prefix: str) -> None:
    with pytest.raises(BadPrefix):
        list_dirs(prefix)


async def test_route(daemon: Daemon, home: Path) -> None:
    use(daemon)
    async with client(daemon) as http:
        ok = await http.get("/api/fs/dirs", params={"prefix": "~/Proj"})
        relative = await http.get("/api/fs/dirs", params={"prefix": "Projects"})
    assert ok.json() == {"dirs": [{"name": "Projects", "path": "~/Projects"}]}
    assert relative.status_code == 400 and "start with / or ~/" in relative.json()["detail"]
