"""The workbench over several folders of one room: naming, routing and every rule per folder.

Everything happens under `tmp_path`; nothing touches the network or the real
home folder. The rules over one folder are covered by `test_workbench.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from vision.core.folders import folder_names
from vision.gate.tools import Tool, ToolFailure
from vision.workbench import project_tools

PROGRAMS = {"sh": Path("/bin/sh"), "python": Path(sys.executable)}


def make(folder: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return folder


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    return make(tmp_path / "work" / "shop-api", {"README.md": "# Shop API\nneedle in shop\n", "src/app.py": "print('shop')\n"})


@pytest.fixture
def blog(tmp_path: Path) -> Path:
    return make(
        tmp_path / "work" / "blog",
        {"notes.txt": "needle in blog\n", ".env": "TOKEN=sk-live-999\n", "deploy.pem": "KEY\n", ".git/config": "[core]\n"},
    )


@pytest.fixture
def tools(shop: Path, blog: Path) -> dict[str, Tool]:
    return {tool.spec.name: tool for tool in project_tools([shop, blog], PROGRAMS)}


async def refused(tool: Tool, **args: Any) -> str:
    with pytest.raises(ToolFailure) as caught:
        await tool.run(args)
    return str(caught.value)


# ---- names -----------------------------------------------------------------------------


def test_names_are_the_folders_own_made_unique() -> None:
    assert folder_names(["~/Projects/shop", "/srv/blog/"]) == ["shop", "blog"]
    assert folder_names(["/a/app", "/b/app", "/c/App", "/d/app-2"]) == ["app", "app-2", "App-3", "app-2-2"]
    assert folder_names(["/x/y/.."]) == ["x"]
    assert folder_names(["/", "/t/~home"]) == ["folder", "home"]


async def test_one_folder_uses_the_same_scheme_so_paths_keep_their_meaning(shop: Path, blog: Path) -> None:
    alone = {t.spec.name: t for t in project_tools([shop], PROGRAMS)}
    both = {t.spec.name: t for t in project_tools([shop, blog], PROGRAMS)}
    for tools in (alone, both):
        assert (await tools["read_file"].run({"path": "shop-api/src/app.py"})).startswith("shop-api/src/app.py:")
        assert tools["run_program"].spec.input_schema["properties"]["folder"]["enum"][0] == "shop-api"
    assert "does not start with one of this room's folders: `shop-api`" in await refused(alone["read_file"], path="src/app.py")


def test_no_folder_or_the_same_folder_twice_is_refused(shop: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        project_tools([], PROGRAMS)
    os.symlink(shop, tmp_path / "again")
    with pytest.raises(ValueError, match="twice"):
        project_tools([shop, tmp_path / "again"], PROGRAMS)


def test_home_among_several_is_refused(shop: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "work"))
    with pytest.raises(ValueError):
        project_tools([shop, tmp_path / "work"], PROGRAMS)


# ---- paths through folder names ----------------------------------------------------------


async def test_list_dot_lists_the_folders(tools: dict[str, Tool], shop: Path) -> None:
    out = await tools["list_files"].run({"path": "."})
    assert out.splitlines()[0].startswith("./ (depth 2): this room's 2 folders")
    assert f"shop-api/  ({os.path.realpath(shop)})" in out and "blog/  (" in out
    assert "  src/" in out and "  .env  [protected: secrets, never read]" in out
    shallow = await tools["list_files"].run({"path": ".", "depth": 1})
    assert "src/" not in shallow and "blog/" in shallow


async def test_paths_start_with_a_folder_name(tools: dict[str, Tool]) -> None:
    read = await tools["read_file"].run({"path": "shop-api/src/app.py"})
    assert read.startswith("shop-api/src/app.py: lines 1-1 of 1")
    assert (await tools["read_file"].run({"path": "BLOG/notes.txt"})).startswith("blog/notes.txt:")
    listing = await tools["list_files"].run({"path": "shop-api/src"})
    assert listing.startswith("shop-api/src/ (depth 2)")


async def test_a_made_up_folder_name_is_refused_with_the_names(tools: dict[str, Tool]) -> None:
    message = await refused(tools["read_file"], path="shop/README.md")
    assert "`shop-api`, `blog`" in message and "does not start with one of this room's folders" in message
    assert "folders" in await refused(tools["read_file"], path=".")
    assert "folders" in await refused(tools["write_file"], path="README.md", content="x")


async def test_a_folder_name_that_is_dotdot_or_absolute_is_refused(tools: dict[str, Tool], tmp_path: Path) -> None:
    assert "`..`" in await refused(tools["read_file"], path="../work/blog/notes.txt")
    assert "`..`" in await refused(tools["read_file"], path="shop-api/../blog/notes.txt")
    assert "Absolute" in await refused(tools["read_file"], path=str(tmp_path / "work" / "blog" / "notes.txt"))
    assert "`~`" in await refused(tools["list_files"], path="~/work")


async def test_a_link_from_one_folder_into_another_is_refused(tools: dict[str, Tool], shop: Path, blog: Path) -> None:
    os.symlink(blog, shop / "to-blog")
    os.symlink(blog / "notes.txt", shop / "notes-link.txt")
    for path in ("shop-api/to-blog/notes.txt", "shop-api/notes-link.txt", "shop-api/to-blog/.env"):
        assert "leads outside the folder `shop-api`" in await refused(tools["read_file"], path=path)
    assert "leads outside" in await refused(tools["write_file"], path="shop-api/to-blog/new.txt", content="x")
    assert not (blog / "new.txt").exists()
    listing = await tools["list_files"].run({"path": "shop-api"})
    assert "to-blog -> (link that leads outside the project; not followed)" in listing
    found = await tools["search_files"].run({"pattern": "needle", "path": "shop-api"})
    assert "blog/notes.txt" not in found


async def test_protected_files_in_the_second_folder(tools: dict[str, Tool], blog: Path) -> None:
    for path in ("blog/.env", "blog/.ENV", "blog/deploy.pem"):
        assert "protected file" in await refused(tools["read_file"], path=path)
    assert "`blog/.env` is a protected file" in await refused(tools["write_file"], path="blog/.env", content="x")
    assert "`.git`" in await refused(tools["write_file"], path="blog/.git/config", content="x")
    assert "hooks" in await refused(tools["write_file"], path="blog/.githooks/pre-commit", content="x")
    found = await tools["search_files"].run({"pattern": "sk-live|KEY"})
    assert "sk-live" not in found and "protected" in found
    assert (blog / ".env").read_text() == "TOKEN=sk-live-999\n"


async def test_search_dot_searches_every_folder(tools: dict[str, Tool]) -> None:
    found = await tools["search_files"].run({"pattern": "needle"})
    assert "shop-api/README.md:2: needle in shop" in found and "blog/notes.txt:1: needle in blog" in found
    only = await tools["search_files"].run({"pattern": "needle", "path": "blog"})
    assert "blog/notes.txt:1:" in only and "shop-api" not in only


async def test_writes_and_edits_land_in_the_named_folder(tools: dict[str, Tool], blog: Path, shop: Path) -> None:
    card = tools["write_file"].describe({"path": "blog/new.txt", "content": "hi\n"})  # type: ignore[misc]
    assert card.startswith("Create new file blog/new.txt (1 lines)") and os.path.realpath(blog) in card
    assert await tools["write_file"].run({"path": "blog/new.txt", "content": "hi\n"}) == "Created blog/new.txt (1 lines)."
    assert (blog / "new.txt").read_text() == "hi\n" and not (shop / "new.txt").exists()
    edit = {"path": "shop-api/src/app.py", "old": "'shop'", "new": "'store'"}
    assert "Edit shop-api/src/app.py" in tools["edit_file"].describe(edit)  # type: ignore[misc]
    assert (await tools["edit_file"].run(edit)).startswith("Edited shop-api/src/app.py")
    assert "That is the folder `blog` itself" in await refused(tools["write_file"], path="blog", content="x")


# ---- run_program -----------------------------------------------------------------------


async def test_a_program_runs_in_the_folder_named(tools: dict[str, Tool], shop: Path, blog: Path) -> None:
    run = tools["run_program"]
    schema = run.spec.input_schema["properties"]["folder"]
    assert schema["enum"] == ["shop-api", "blog"]
    args = {"program": "sh", "args": ["-c", "pwd"], "folder": "blog"}
    card = run.describe(args)  # type: ignore[misc]
    assert f"In the folder: {os.path.realpath(blog)}\n" in card and "/bin/sh -c pwd" in card
    assert (await run.run(args)).splitlines()[1] == os.path.realpath(blog)
    first = await run.run({"program": "sh", "args": ["-c", "pwd"]})
    assert first.splitlines()[1] == os.path.realpath(shop)


async def test_a_program_in_a_made_up_folder_is_refused(tools: dict[str, Tool]) -> None:
    run = tools["run_program"]
    for folder in ("nowhere", "..", "/tmp", 3):
        message = await refused(run, program="sh", args=["-c", "pwd"], folder=folder)
        assert "`shop-api`, `blog`" in message
    assert "will be refused" in run.describe({"program": "sh", "args": [], "folder": "nowhere"})  # type: ignore[misc]


async def test_two_folders_with_the_same_name(tmp_path: Path) -> None:
    first = make(tmp_path / "a" / "app", {"which.txt": "first\n"})
    second = make(tmp_path / "b" / "app", {"which.txt": "second\n", ".env": "SECRET=1\n"})
    tools = {t.spec.name: t for t in project_tools([first, second], PROGRAMS)}
    assert (await tools["read_file"].run({"path": "app/which.txt"})).endswith("first")
    assert (await tools["read_file"].run({"path": "app-2/which.txt"})).endswith("second")
    assert "protected" in await refused(tools["read_file"], path="app-2/.env")
    out = await tools["run_program"].run({"program": "sh", "args": ["-c", "pwd"], "folder": "app-2"})
    assert out.splitlines()[1] == os.path.realpath(second)
