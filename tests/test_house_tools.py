"""Room tools: the catalog, proposals from a project folder, validation and the plan."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from vision.app import Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.house import GridHouse, HouseError, propose_tools, store
from vision.house.parse import build_layout
from vision.house.tools import (
    CATALOG_FILE,
    ToolInfo,
    available,
    catalog_entries,
    load_catalog,
    tool_refs,
)

BUILT_IN = ["remember", "recall", "open_app", "open_url", "shell"]
PROJECT = ["git", "gh", "npm", "maven", "gradle", "python", "docker", "xcode", "unity", "godot"]


def make(root: Path, *paths: str) -> Path:
    """Create files (or folders, for a trailing slash) under `root`."""
    for rel in paths:
        target = root / rel
        if rel.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("")
    return root


# ------------------------------------------------------------ catalog


def test_catalog_loads_in_order() -> None:
    catalog = load_catalog()
    assert list(catalog) == [*BUILT_IN, *PROJECT]
    assert all(catalog[t].built_in and catalog[t].program is None for t in BUILT_IN)
    assert all(not catalog[t].built_in and catalog[t].program for t in PROJECT)
    assert all(t.title and t.description for t in catalog.values())


def test_catalog_refuses_a_tool_with_both_or_neither(tmp_path: Path) -> None:
    bad = tmp_path / "tools.toml"
    bad.write_text('[tools.x]\ntitle = "X"\nbuilt_in = true\nprogram = "x"\n')
    with pytest.raises(HouseError, match="either built_in"):
        load_catalog(bad)
    bad.write_text('[tools.y]\ntitle = "Y"\n')
    with pytest.raises(HouseError, match="either built_in"):
        load_catalog(bad)


def test_availability_follows_the_program() -> None:
    catalog = load_catalog()
    present = {"git"}

    def finder(name: str) -> Path | None:
        return Path("/bin") / name if name in present else None

    assert available(catalog["shell"], finder)
    assert available(catalog["git"], finder)
    assert not available(catalog["gh"], finder)
    refs = tool_refs(["shell", "git", "gh"], catalog, finder)
    assert refs == [
        {"id": "shell", "title": "Shell", "available": True, "built_in": True},
        {"id": "git", "title": "Git", "available": True, "built_in": False},
        {"id": "gh", "title": "GitHub", "available": False, "built_in": False},
    ]
    entry = next(e for e in catalog_entries(catalog, finder) if e["id"] == "npm")
    assert entry["program"] == "npm" and entry["available"] is False
    assert set(entry) == {"id", "title", "description", "program", "built_in", "available"}


# ------------------------------------------------------------ proposals


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        ((".git/",), ["git"]),
        (("package.json",), ["npm"]),
        (("pom.xml",), ["maven"]),
        (("build.gradle",), ["gradle"]),
        (("build.gradle.kts",), ["gradle"]),
        (("pyproject.toml",), ["python"]),
        (("requirements.txt",), ["python"]),
        (("Dockerfile",), ["docker"]),
        (("compose.yaml",), ["docker"]),
        (("docker-compose.yml",), ["docker"]),
        (("App.xcodeproj/",), ["xcode"]),
        (("App.xcworkspace/",), ["xcode"]),
        (("ProjectSettings/ProjectVersion.txt",), ["unity"]),
        (("project.godot",), ["godot"]),
        (("web/package.json", "api/pom.xml"), ["npm", "maven"]),
        (("README.md", "src/"), []),
    ],
)
def test_each_marker(tmp_path: Path, paths: tuple[str, ...], expected: list[str]) -> None:
    assert propose_tools(make(tmp_path / "p", *paths)) == expected


def test_github_remote_proposes_gh(tmp_path: Path) -> None:
    for url in ("git@github.com:someone/thing.git", "https://GitHub.com/someone/thing"):
        root = make(tmp_path / url.replace("/", "_"), ".git/")
        (root / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {url}\n')
        assert propose_tools(root) == ["git", "gh"]
    other = make(tmp_path / "other", ".git/")
    (other / ".git" / "config").write_text('[remote "origin"]\n\turl = https://gitlab.com/a/b\n')
    assert propose_tools(other) == ["git"]


def test_proposal_stays_in_the_top_two_levels(tmp_path: Path) -> None:
    assert propose_tools(make(tmp_path / "p", "a/b/package.json")) == []


def test_proposal_never_follows_symlinks(tmp_path: Path) -> None:
    outside = make(tmp_path / "outside", "package.json", "pom.xml")
    root = tmp_path / "p"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / "Dockerfile").symlink_to(outside / "pom.xml")
    assert propose_tools(root) == []


def test_proposal_expands_home_and_refuses_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    make(tmp_path / "proj", "project.godot")
    assert propose_tools("~/proj") == ["godot"]
    with pytest.raises(NotADirectoryError):
        propose_tools(tmp_path / "proj" / "project.godot")


# ------------------------------------------------------------ the house file


def build(config: Config, user: dict[str, Any]) -> Any:
    return build_layout(store.read_toml(store.DEFAULT_FILE), user, config)


def test_default_house_keeps_working(config: Config) -> None:
    layout = build(config, {})
    assert layout.agents["host"].tools == tuple(BUILT_IN)
    assert layout.agents["maker"].tools == ()
    assert all(r.tools is None for r in layout.rooms)


def test_unknown_tool_ids_are_refused_with_the_known_ones(config: Config) -> None:
    room = {"name": "Den", "agent": "maker", "at": [4, 1], "tools": ["git", "hammer"]}
    with pytest.raises(HouseError, match=r"no tool 'hammer'\. Known tools: remember, .*godot"):
        build(config, {"rooms": [room]})
    with pytest.raises(HouseError, match="no tool 'saw'"):
        build(config, {"agents": {"maker": {"tools": ["saw"]}}})
    with pytest.raises(HouseError, match="must be a list of tool ids"):
        build(config, {"rooms": [{**room, "tools": "git"}]})


def test_room_tools_win_over_the_agent(config: Config) -> None:
    house = GridHouse(config, Bus())
    store.ensure_user_file(config.paths.house_file, store.DEFAULT_FILE)
    text = config.paths.house_file.read_text()
    text = text.replace('model = "claude-opus-5-5"\n', 'model = "claude-opus-5-5"\ntools = ["git"]\n', 1)
    text += '\n[[rooms]]\nname = "Den"\nagent = "maker"\nat = [4, 1]\ntools = ["npm", "npm", "gh"]\n'
    config.paths.house_file.write_text(text)
    rooms = {r["id"]: r for r in house.plan()["rooms"]}
    assert [t["id"] for t in rooms["den"]["tools"]] == ["npm", "gh"]
    assert [t["id"] for t in rooms["workshop"]["tools"]] == ["git"]
    assert [t["id"] for t in rooms["hall"]["tools"]] == BUILT_IN
    assert rooms["library"]["tools"][0] == {
        "id": "remember",
        "title": "Remember",
        "available": True,
        "built_in": True,
    }


async def test_add_and_edit_room_tools(config: Config) -> None:
    house = GridHouse(config, Bus())
    try:
        room = await house.add_room({"name": "Den", "agent": "maker", "tools": ["git", "npm"]})
        assert [t["id"] for t in room["tools"]] == ["git", "npm"]
        room = await house.update_room("den", {"tools": []})
        assert room["tools"] == []
        room = await house.update_room("den", {"tools": None})
        assert room["tools"] == []  # back to the maker's, which has none
        room = await house.update_room("hall", {"tools": ["shell"]})
        assert [t["id"] for t in room["tools"]] == ["shell"]
        with pytest.raises(HouseError, match="no tool 'drill'"):
            await house.update_room("hall", {"tools": ["drill"]})
    finally:
        await house.close()


# ------------------------------------------------------------ routes


def client(d: Daemon, *, token: bool = True) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {d.token}"} if token else {}
    return httpx.AsyncClient(base_url=f"http://127.0.0.1:{d.port}", headers=headers)


async def test_tool_routes_need_the_token(daemon: Daemon) -> None:
    async with client(daemon, token=False) as http:
        assert (await http.get("/api/house/tools")).status_code == 401
        assert (await http.get("/api/house/tools/propose", params={"project": "/"})).status_code == 401


async def test_catalog_route(daemon: Daemon) -> None:
    async with client(daemon) as http:
        tools = (await http.get("/api/house/tools")).json()["tools"]
    assert [t["id"] for t in tools] == [*BUILT_IN, *PROJECT]
    assert all(isinstance(t["available"], bool) for t in tools)


async def test_propose_route(daemon: Daemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    make(tmp_path / "app", "package.json", "Dockerfile")
    async with client(daemon) as http:
        ok = await http.get("/api/house/tools/propose", params={"project": "~/app"})
        missing = await http.get("/api/house/tools/propose", params={"project": "~/nowhere"})
        a_file = await http.get("/api/house/tools/propose", params={"project": "~/app/Dockerfile"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["project"] == str(tmp_path / "app")
    assert [t["id"] for t in body["tools"]] == ["npm", "docker"]
    assert set(body["tools"][0]) == {"id", "title", "available", "built_in"}
    assert missing.status_code == 400 and "is not a folder" in missing.json()["detail"]
    assert a_file.status_code == 400


async def test_room_routes_accept_tools(daemon: Daemon) -> None:
    async with client(daemon) as http:
        added = await http.post(
            "/api/house/rooms", json={"name": "Den", "agent": "maker", "at": [4, 1], "tools": ["git"]}
        )
        assert [t["id"] for t in added.json()["room"]["tools"]] == ["git"]
        edited = await http.patch("/api/house/rooms/den", json={"tools": ["gh", "docker"]})
        assert [t["id"] for t in edited.json()["room"]["tools"]] == ["gh", "docker"]
        refused = await http.patch("/api/house/rooms/den", json={"tools": ["laser"]})
    assert refused.status_code == 400
    assert "Known tools:" in refused.json()["detail"]


def test_catalog_file_is_in_the_repo() -> None:
    assert CATALOG_FILE.is_file()
    assert isinstance(next(iter(load_catalog().values())), ToolInfo)
