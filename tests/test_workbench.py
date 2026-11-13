"""The workbench tools: every safety rule attacked, and the ordinary cases.

Everything happens under `tmp_path`; nothing touches the network or the real
home folder. Programs used are system ones (/bin/sh, /usr/bin/env) and the
test's own Python.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from vision.gate.tools import Tool, ToolFailure
from vision.workbench import NAMES, project_tools
from vision.workbench import programs as programs_mod
from vision.workbench import search as search_mod
from vision.workbench.protected import is_protected_name

PROGRAMS = {"sh": Path("/bin/sh"), "env": Path("/usr/bin/env"), "python": Path(sys.executable)}


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "secret.txt").write_text("OUTSIDE-SECRET\n")
    return folder


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# Demo\nhello world\n")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("".join(f"line {i}\n" for i in range(1, 51)))
    (root / "src" / "util.ts").write_text("export const hello = 1;\n")
    (root / ".env").write_text("API_KEY=sk-live-123\n")
    (root / ".env.example").write_text("API_KEY=\n")
    (root / "deploy.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
    (root / ".git" / "hooks").mkdir(parents=True)
    (root / ".git" / "config").write_text("[core]\n\tbare = false\n")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("hello from deps\n")
    return root


@pytest.fixture
def tools(project: Path) -> dict[str, Tool]:
    return {tool.spec.name: tool for tool in project_tools(project, PROGRAMS)}


async def refused(tool: Tool, **args: Any) -> str:
    with pytest.raises(ToolFailure) as caught:
        await tool.run(args)
    return str(caught.value)


# ---- shape -----------------------------------------------------------------------------


def test_tools_in_fixed_order(tools: dict[str, Tool]) -> None:
    assert tuple(tools) == NAMES == (
        "list_files", "read_file", "search_files", "write_file", "edit_file", "run_program"
    )
    for tool in tools.values():
        assert tool.spec.input_schema["additionalProperties"] is False
    assert tools["write_file"].describe and tools["edit_file"].describe and tools["run_program"].describe


def test_root_may_not_be_home_or_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError):
        project_tools(tmp_path, {})
    with pytest.raises(ValueError):
        project_tools(Path("/"), {})


def test_program_list_is_checked(project: Path) -> None:
    with pytest.raises(ValueError):
        project_tools(project, {"git": Path("git")})
    with pytest.raises(ValueError):
        project_tools(project, {"../git": Path("/usr/bin/git")})


# ---- rule 1: nothing outside the root --------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["../outside/secret.txt", "src/../../outside/secret.txt", "..", "~/secret.txt", "~", "", "   ", "src/\x00app.py"],
)
async def test_odd_and_escaping_paths_are_refused(tools: dict[str, Tool], outside: Path, path: str) -> None:
    message = await refused(tools["read_file"], path=path)
    assert "OUTSIDE-SECRET" not in message


async def test_absolute_paths_are_refused_without_echo(tools: dict[str, Tool], outside: Path) -> None:
    target = str(outside / "secret.txt")
    for name, args in [
        ("read_file", {"path": target}),
        ("list_files", {"path": str(outside)}),
        ("search_files", {"pattern": "SECRET", "path": str(outside)}),
        ("write_file", {"path": target, "content": "x"}),
    ]:
        message = await refused(tools[name], **args)
        assert "Absolute paths are not allowed" in message
        assert str(outside) not in message
    assert (outside / "secret.txt").read_text() == "OUTSIDE-SECRET\n"


async def test_symlink_to_file_outside(tools: dict[str, Tool], project: Path, outside: Path) -> None:
    (project / "link.txt").symlink_to(outside / "secret.txt")
    message = await refused(tools["read_file"], path="link.txt")
    assert "outside the project" in message and str(outside) not in message


async def test_symlinked_folder_leading_out(tools: dict[str, Tool], project: Path, outside: Path) -> None:
    (project / "docs").symlink_to(outside)
    assert "outside the project" in await refused(tools["read_file"], path="docs/secret.txt")
    assert "outside the project" in await refused(tools["list_files"], path="docs")
    # A link in the middle of a path, and as the parent of a file about to be created.
    assert "outside the project" in await refused(tools["write_file"], path="docs/new/deep.txt", content="x")
    assert not (outside / "new").exists()
    listing = await tools["list_files"].run({})
    assert "docs -> (link that leads outside the project; not followed)" in listing
    assert "secret.txt" not in listing and str(outside) not in listing


async def test_symlink_to_etc_is_never_followed(tools: dict[str, Tool], project: Path) -> None:
    (project / "sys").symlink_to("/etc")
    assert "outside the project" in await refused(tools["read_file"], path="sys/hosts")
    found = await tools["search_files"].run({"pattern": "localhost"})
    assert "sys/" not in found
    listing = await tools["list_files"].run({"depth": 3})
    assert "hosts" not in listing


async def test_writing_through_a_symlink_is_refused(tools: dict[str, Tool], project: Path, outside: Path) -> None:
    (project / "notes.txt").symlink_to(outside / "secret.txt")
    assert "outside the project" in await refused(tools["write_file"], path="notes.txt", content="pwned")
    assert "outside the project" in await refused(tools["edit_file"], path="notes.txt", old="OUTSIDE", new="x")
    assert (outside / "secret.txt").read_text() == "OUTSIDE-SECRET\n"
    assert (project / "notes.txt").is_symlink()


async def test_symlink_loop_is_refused(tools: dict[str, Tool], project: Path) -> None:
    (project / "a").symlink_to(project / "b")
    (project / "b").symlink_to(project / "a")
    await refused(tools["read_file"], path="a")


async def test_link_inside_the_project_works(tools: dict[str, Tool], project: Path) -> None:
    (project / "readme-link").symlink_to(project / "README.md")
    assert "hello world" in await tools["read_file"].run({"path": "readme-link"})


# ---- rule 2: secrets -------------------------------------------------------------------


async def test_env_read_is_refused(tools: dict[str, Tool], project: Path) -> None:
    for path in (".env", ".ENV", "./.env"):
        message = await refused(tools["read_file"], path=path)
        assert "protected" in message and "sk-live" not in message
    (project / "config.txt").symlink_to(project / ".env")
    assert "protected" in await refused(tools["read_file"], path="config.txt")
    assert "API_KEY=" in await tools["read_file"].run({"path": ".env.example"})


async def test_env_is_not_found_by_search(tools: dict[str, Tool], project: Path) -> None:
    (project / "sub").mkdir()
    (project / "sub" / ".env.production").write_text("API_KEY=sk-live-456\n")
    found = await tools["search_files"].run({"pattern": "sk-live"})
    assert "sk-live" not in found and "No matches" in found
    found = await tools["search_files"].run({"pattern": "API_KEY"})
    assert ".env.example:1" in found and ".env:" not in found and "production" not in found
    assert "protected" in await refused(tools["search_files"], pattern="x", path=".env")


async def test_key_file_edit_and_write_are_refused(tools: dict[str, Tool], project: Path) -> None:
    assert "protected" in await refused(tools["edit_file"], path="deploy.pem", old="BEGIN", new="END")
    assert "protected" in await refused(tools["write_file"], path="keys/id_rsa", content="x")
    assert "protected" in await refused(tools["write_file"], path=".ssh/config", content="x")
    assert (project / "deploy.pem").read_text().startswith("-----BEGIN")
    assert not (project / "keys").exists()


async def test_protected_files_are_listed_but_marked(tools: dict[str, Tool]) -> None:
    listing = await tools["list_files"].run({})
    assert ".env  [protected" in listing and "deploy.pem  [protected" in listing
    assert "sk-live" not in listing
    assert ".env.example  (" in listing


@pytest.mark.parametrize(
    "name",
    [".env", ".env.local", ".envrc", "server.key", "cert.p12", "a.pfx", "release.keystore", "upload.jks",
     "id_rsa", "id_ed25519.pub", "id_ecdsa", ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".ssh", ".aws",
     ".gnupg", "credentials.json", "secrets.yaml", "prod.tfvars", "my-service-account.json",
     "Dist.mobileprovision", "AuthKey_ABC.p8", "key.properties", "client_secret_123.json"],
)
def test_protected_names(name: str) -> None:
    assert is_protected_name(name)


@pytest.mark.parametrize("name", [".env.example", ".env.sample", "app.py", "keyboard.ts", "README.md", "environment.ts"])
def test_ordinary_names(name: str) -> None:
    assert not is_protected_name(name)


# ---- rule 3: .git and hooks ------------------------------------------------------------


async def test_git_folder_and_hooks_are_never_written(tools: dict[str, Tool], project: Path) -> None:
    hook = "#!/bin/sh\ncurl evil\n"
    for path in (".git/hooks/pre-commit", ".GIT/hooks/post-checkout", ".git/config", ".githooks/pre-push", ".husky/pre-commit"):
        message = await refused(tools["write_file"], path=path, content=hook)
        assert "git" in message
    assert "never written" in await refused(tools["edit_file"], path=".git/config", old="bare", new="x")
    assert not (project / ".git" / "hooks" / "pre-commit").exists()
    (project / "g").symlink_to(project / ".git")
    assert "never written" in await refused(tools["write_file"], path="g/hooks/pre-commit", content=hook)
    assert not list((project / ".git" / "hooks").iterdir())


async def test_configured_hooks_path_is_never_written(project: Path) -> None:
    (project / ".git" / "config").write_text("[core]\n\thooksPath = tools/hooks\n")
    tools = {t.spec.name: t for t in project_tools(project, {})}
    assert "hooks" in await refused(tools["write_file"], path="tools/hooks/pre-commit", content="x")
    await tools["write_file"].run({"path": "tools/other.sh", "content": "x"})


# ---- rule 4: clean environment ----------------------------------------------------------


async def test_secret_environment_never_reaches_the_child(tools: dict[str, Tool], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak")
    monkeypatch.setenv("VISION_HOME_SECRET", "vision-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-leak")
    monkeypatch.setenv("DB_PASSWORD", "pw-leak")
    monkeypatch.setenv("SOME_RANDOM_THING", "random-leak")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    output = await tools["run_program"].run({"program": "env", "args": []})
    assert output.startswith("exit code 0")
    for leak in ("sk-ant-leak", "vision-leak", "ghp-leak", "pw-leak", "random-leak", "ANTHROPIC", "VISION_"):
        assert leak not in output
    names = {line.split("=", 1)[0] for line in output.splitlines()[1:] if "=" in line}
    assert {"PATH", "HOME", "LANG"} <= names
    assert not any(programs_mod.is_secret_name(name) for name in names)


async def test_child_has_no_stdin_and_runs_in_root(tools: dict[str, Tool], project: Path) -> None:
    output = await tools["run_program"].run({"program": "sh", "args": ["-c", "pwd; cat; echo done"]})
    assert os.path.realpath(project) in output and output.rstrip().endswith("done")


# ---- rule 5: programs and arguments ------------------------------------------------------


async def test_unknown_program_is_refused(tools: dict[str, Tool]) -> None:
    message = await refused(tools["run_program"], program="curl", args=["http://example.com"])
    assert "allowed program ids" in message and "env, python, sh" in message


async def test_program_given_as_a_path_is_refused(tools: dict[str, Tool]) -> None:
    for program in ("/bin/sh", "/usr/bin/env", "./sh", "sh ", "SH"):
        assert "allowed program ids" in await refused(tools["run_program"], program=program, args=[])


async def test_arguments_are_checked(tools: dict[str, Tool]) -> None:
    run = tools["run_program"]
    assert "NUL" in await refused(run, program="sh", args=["-c", "echo\x00hi"])
    assert "list of strings" in await refused(run, program="sh", args="-c echo hi")
    assert "list of strings" in await refused(run, program="sh", args=["-c", 3])
    assert "Too many" in await refused(run, program="sh", args=["x"] * (programs_mod.MAX_ARGS + 1))
    assert "longer than" in await refused(run, program="sh", args=["x" * (programs_mod.MAX_ARGS_CHARS + 1)])


async def test_no_shell_between_model_and_program(tools: dict[str, Tool], project: Path) -> None:
    output = await tools["run_program"].run({"program": "python", "args": ["-c", "import sys; print(sys.argv[1:])", "$(touch pwned)", ";", "|"]})
    assert "['$(touch pwned)', ';', '|']" in output
    assert not (project / "pwned").exists()


async def test_hanging_program_is_killed_with_its_children(tools: dict[str, Tool], project: Path) -> None:
    script = "sleep 60 & echo $! > child.pid; sleep 60"
    started = time.monotonic()
    message = await refused(tools["run_program"], program="sh", args=["-c", script], timeout_s=1)
    assert time.monotonic() - started < 10
    assert "did not finish within 1 seconds" in message
    child = int((project / "child.pid").read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("the hanging program's child is still running")


async def test_cancel_kills_the_program(tools: dict[str, Tool], project: Path) -> None:
    task = asyncio.create_task(tools["run_program"].run({"program": "sh", "args": ["-c", "echo $$ > me.pid; sleep 60"]}))
    for _ in range(50):
        if (project / "me.pid").exists() and (project / "me.pid").read_text().strip():
            break
        await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pid = int((project / "me.pid").read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.1)
    pytest.fail("the cancelled program is still running")


async def test_output_larger_than_the_cap_is_cut(tools: dict[str, Tool]) -> None:
    output = await tools["run_program"].run({"program": "python", "args": ["-c", "print('x' * 200000)"]})
    assert len(output) < programs_mod.OUTPUT_LIMIT + 500
    assert f"output cut at {programs_mod.OUTPUT_LIMIT} bytes" in output


async def test_exit_code_and_output_are_reported(tools: dict[str, Tool]) -> None:
    output = await tools["run_program"].run({"program": "sh", "args": ["-c", "echo out; echo err >&2; exit 3"]})
    assert output.splitlines()[0] == "exit code 3" and "out" in output and "err" in output


async def test_timeout_is_capped(tools: dict[str, Tool]) -> None:
    card = tools["run_program"].describe({"program": "sh", "args": ["-c", "true"], "timeout_s": 99999})  # type: ignore[misc]
    assert f"Stopped after {programs_mod.MAX_TIMEOUT_S:g} seconds" in card


def test_clean_environment_filters_names() -> None:
    env = programs_mod.clean_environment({"git": Path("/opt/tools/bin/git")}, {"HOME": "/h", "USER": "me", "AWS_SECRET_ACCESS_KEY": "x"})
    assert env["PATH"].split(":")[0] == "/opt/tools/bin"
    assert "AWS_SECRET_ACCESS_KEY" not in env and env["USER"] == "me"


# ---- search guard ------------------------------------------------------------------------


async def test_catastrophic_regex_is_stopped(tools: dict[str, Tool], project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_mod, "SEARCH_TIMEOUT_S", 1.5)
    (project / "evil.txt").write_text("a" * 40 + "!\n")
    started = time.monotonic()
    message = await refused(tools["search_files"], pattern="^(a+)+$", glob="evil.txt")
    assert time.monotonic() - started < 10
    assert "stopped" in message and "backtrack" in message


async def test_invalid_regex_is_explained(tools: dict[str, Tool]) -> None:
    assert "not a valid" in await refused(tools["search_files"], pattern="(unclosed")


async def test_search_caps_matches_and_line_length(tools: dict[str, Tool], project: Path) -> None:
    (project / "many.txt").write_text("hit\n" * (search_mod.MAX_MATCHES + 50))
    (project / "long.txt").write_text("x" * 5000 + "needle" + "y" * 5000 + "\n")
    found = await tools["search_files"].run({"pattern": "hit", "glob": "many.txt"})
    assert f"stopped at {search_mod.MAX_MATCHES} matches" in found
    found = await tools["search_files"].run({"pattern": "needle", "glob": "long.txt"})
    line = found.splitlines()[1]
    assert "needle" in line and len(line) < search_mod.SHOWN_LINE_CHARS + 50


# ---- ordinary cases ------------------------------------------------------------------------


async def test_list(tools: dict[str, Tool]) -> None:
    listing = await tools["list_files"].run({})
    assert "src/" in listing and "  app.py  (" in listing and "README.md  (" in listing
    assert "node_modules/  [skipped" in listing and ".git/  [skipped" in listing
    assert "index.js" not in listing
    shallow = await tools["list_files"].run({"depth": 1})
    assert "src/  [not expanded]" in shallow and "app.py" not in shallow
    deps = await tools["list_files"].run({"path": "node_modules"})
    assert "pkg/" in deps


async def test_list_caps_entries(tools: dict[str, Tool], project: Path) -> None:
    (project / "many").mkdir()
    for i in range(500):
        (project / "many" / f"f{i:03}.txt").write_text("x")
    listing = await tools["list_files"].run({"path": "many"})
    assert "[cut at 400 entries" in listing


async def test_ranged_read(tools: dict[str, Tool]) -> None:
    text = await tools["read_file"].run({"path": "src/app.py", "start_line": 10, "end_line": 12})
    assert text.splitlines() == ["src/app.py: lines 10-12 of 50", "10\tline 10", "11\tline 11", "12\tline 12", "[cut after line 12 of 50 (the default range); call read_file with start_line=13 to read on]"]
    whole = await tools["read_file"].run({"path": "README.md"})
    assert whole.splitlines()[0] == "README.md: lines 1-2 of 2"
    assert "past the end" in await refused(tools["read_file"], path="README.md", start_line=10)


async def test_big_read_is_cut_with_a_way_on(tools: dict[str, Tool], project: Path) -> None:
    (project / "big.txt").write_text("".join(f"{'z' * 100} {i}\n" for i in range(3000)))
    text = await tools["read_file"].run({"path": "big.txt"})
    assert len(text) < 62_000 and "call read_file with start_line=" in text


async def test_binary_file_read_is_refused(tools: dict[str, Tool], project: Path) -> None:
    (project / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert "binary" in await refused(tools["read_file"], path="logo.png")


async def test_fifo_read_is_refused(tools: dict[str, Tool], project: Path) -> None:
    os.mkfifo(project / "pipe")
    assert "not a regular file" in await refused(tools["read_file"], path="pipe")


async def test_search_with_glob(tools: dict[str, Tool]) -> None:
    found = await tools["search_files"].run({"pattern": "hello", "glob": "*.ts"})
    assert "src/util.ts:1: export const hello = 1;" in found and "README" not in found
    found = await tools["search_files"].run({"pattern": "HELLO", "ignore_case": True})
    assert "README.md:2: hello world" in found and "node_modules" not in found
    found = await tools["search_files"].run({"pattern": "line 4\\d", "path": "src", "glob": "src/**/*.py"})
    assert "src/app.py:40: line 40" in found


async def test_write_new_and_replace(tools: dict[str, Tool], project: Path) -> None:
    assert await tools["write_file"].run({"path": "docs/guide/intro.md", "content": "a\nb\n"}) == "Created docs/guide/intro.md (2 lines)."
    assert (project / "docs/guide/intro.md").read_text() == "a\nb\n"
    os.chmod(project / "docs/guide/intro.md", 0o600)
    assert await tools["write_file"].run({"path": "docs/guide/intro.md", "content": "c\n"}) == "Replaced docs/guide/intro.md (now 1 lines)."
    assert (project / "docs/guide/intro.md").read_text() == "c\n"
    assert oct((project / "docs/guide/intro.md").stat().st_mode & 0o777) == oct(0o600)
    assert not [p for p in (project / "docs/guide").iterdir() if p.name.endswith(".tmp")]


async def test_write_size_cap(tools: dict[str, Tool]) -> None:
    assert "more than" in await refused(tools["write_file"], path="huge.txt", content="x" * 1_000_001)


async def test_edit_unique_and_not_unique(tools: dict[str, Tool], project: Path) -> None:
    (project / "a.txt").write_text("one\ntwo\ntwo\nthree\n")
    assert "Edited a.txt" in await tools["edit_file"].run({"path": "a.txt", "old": "one\n", "new": "uno\n"})
    assert (project / "a.txt").read_text() == "uno\ntwo\ntwo\nthree\n"
    assert "more than once" in await refused(tools["edit_file"], path="a.txt", old="two", new="dos")
    assert "not found" in await refused(tools["edit_file"], path="a.txt", old="four", new="x")
    (project / "b.txt").write_text("aaa")
    assert "more than once" in await refused(tools["edit_file"], path="b.txt", old="aa", new="b")
    assert (project / "a.txt").read_text() == "uno\ntwo\ntwo\nthree\n"


# ---- cards -------------------------------------------------------------------------------


def test_describe_write(tools: dict[str, Tool], project: Path) -> None:
    describe = tools["write_file"].describe
    assert describe is not None
    card = describe({"path": "new/file.py", "content": "print(1)\nprint(2)\n"})
    assert card.startswith("Create new file new/file.py (2 lines)") and "print(2)" in card
    card = describe({"path": "README.md", "content": "x\n" * 100})
    assert card.startswith("Replace README.md (2 lines) with 100 lines") and "more lines not shown" in card
    card = describe({"path": "x.txt", "content": "safe‮evil"})
    assert "\\u202e" in card
    assert describe({"path": ".env", "content": "x"}).startswith("This request will be refused")
    assert describe({"path": None}).startswith("This request will be refused")


def test_describe_edit(tools: dict[str, Tool]) -> None:
    describe = tools["edit_file"].describe
    assert describe is not None
    card = describe({"path": "README.md", "old": "hello world", "new": "hi there"})
    assert card.startswith("Edit README.md") and "Replace:\nhello world" in card and "With:\nhi there" in card
    assert "refused" in describe({"path": "README.md", "old": "absent", "new": "x"})


def test_describe_run(tools: dict[str, Tool], project: Path) -> None:
    describe = tools["run_program"].describe
    assert describe is not None
    card = describe({"program": "sh", "args": ["-c", "echo 'hi there'; rm -rf x", "a\nb"]})
    assert "/bin/sh -c 'echo '\"'\"'hi there'\"'\"'; rm -rf x' $'a\\nb'" in card
    assert f"In the folder: {os.path.realpath(project)}" in card and "Stopped after 120 seconds" in card
    assert describe({"program": "/bin/sh", "args": []}).startswith("This request will be refused")
