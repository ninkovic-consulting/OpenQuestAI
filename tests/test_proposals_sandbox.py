"""The confinement of made tools, proved with real child processes.

Every breakout test has a control: the same action run unconfined, in the
same folder with the same environment, must succeed, so a refusal is the
sandbox's doing and not this test environment's. Nothing here touches the
network beyond 127.0.0.1, the Keychain or the real home: the "home" is a
folder in tmp_path and `Path.home` points at it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from vision.proposals import sandbox
from vision.proposals.sandbox import Language, Reach, RunResult, Unavailable, run_confined
from vision.workbench.protected import is_protected_name

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or sandbox.problem() is not None,
    reason=f"confinement unavailable: {sandbox.problem()}",
)

DENIED = "DENIED"


@dataclass
class Layout:
    home: Path
    assistant: Path
    """The assistant's own home (`deny` in every run), with the scratch inside it as in the daemon."""
    scratch: Path
    project: Path
    outside: Path

    async def run(
        self,
        language: Language,
        script: str,
        *,
        read: Sequence[Path] = (),
        network: bool = False,
        stdin: bytes = b"",
        env: dict[str, str] | None = None,
        timeout: float = 20.0,
        limit: int = 20_000,
    ) -> RunResult:
        return await run_confined(
            language,
            script,
            stdin,
            reach=Reach(read=tuple(read), network=network),
            scratch=self.scratch,
            deny=(self.assistant,),
            env_extra=env or {},
            timeout=timeout,
            limit=limit,
        )

    def free(self, language: Language, script: str, *, stdin: bytes = b"", env: dict[str, str] | None = None) -> str:
        """The control: the same script, unconfined, same folder and environment."""
        python, _ = sandbox._python()
        argv = [python, "-I", "-S", "-B", "-c", script] if language == "python" else ["/bin/sh", "-c", script]
        done = subprocess.run(
            argv,
            cwd=self.scratch,
            env=sandbox._environment(self.scratch, env or {}),
            input=stdin,
            capture_output=True,
            timeout=20,
            check=False,
        )
        return (done.stdout + done.stderr).decode()


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Layout:
    home = Path(os.path.realpath(tmp_path)) / "user"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_rsa").write_text("PRIVATE KEY\n")
    (home / "notes.txt").write_text("plain notes\n")
    assistant = home / ".vision"
    (assistant / "made-tools" / "scratch" / "run1").mkdir(parents=True)
    (assistant / "memory.db").write_text("the assistant's memory\n")
    project = home / "Projects" / "shop"
    (project / "secrets").mkdir(parents=True)
    (project / "readme.txt").write_text("hello shop\n")
    (project / ".env").write_text("API_KEY=abc\n")
    (project / ".env.example").write_text("API_KEY=\n")
    (project / "Deploy.PEM").write_text("cert\n")
    (project / "secrets" / "notes.txt").write_text("hidden\n")
    outside = home / "outside"
    outside.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return Layout(home, assistant, assistant / "made-tools" / "scratch" / "run1", project, outside)


def read_script(path: Path) -> str:
    return (
        "import sys\n"
        f"try:\n    print(open({str(path)!r}).read().strip())\n"
        f"except OSError:\n    print({DENIED!r})\n"
    )


def write_script(path: Path) -> str:
    return (
        f"try:\n    open({str(path)!r}, 'w').write('x')\n    print('WROTE')\n"
        f"except OSError:\n    print({DENIED!r})\n"
    )


# --- Availability and the words for the owner ----------------------------------------


def test_available_here_with_words_for_the_owner() -> None:
    assert sandbox.problem() is None
    assert sandbox.ENFORCED and sandbox.NOT_ENFORCED
    assert all(line.endswith(".") for line in sandbox.ENFORCED + sandbox.NOT_ENFORCED)


async def test_refuses_rather_than_runs_unconfined(layout: Layout, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "problem", lambda: "no sandbox here")
    with pytest.raises(Unavailable, match="no sandbox here"):
        await layout.run("sh", "echo ran > ran")
    assert not (layout.scratch / "ran").exists()


def test_the_profile_names_paths_only_as_parameters(layout: Layout) -> None:
    marks = sandbox._Marks(read="/m.r", denied="/m.d")
    argv = sandbox._argv(
        "sh",
        "true",
        reach=Reach(read=(layout.project,), network=False),
        scratch=str(layout.scratch),
        marks=marks,
        deny=(layout.assistant,),
        cpu=5,
    )
    profile = argv[argv.index("-p") + 1]
    assert str(layout.home) not in profile
    assert f"READ0={layout.project}" in argv and f"DENY0={layout.assistant}" in argv


NAMES = [
    ".env", ".ENV", ".env.local", ".env.", ".env.e", ".env.exampl", ".env.examples", ".env.sample.bak",
    ".env.example", ".Env.Sample", ".envrc", "env", "id_rsa", "id_rsa.pub", "a.pem", "B.Key", "x.p8", "secrets",
    "secretsx", "my-secrets", "credentials.json", "readme.txt", "key.properties", "main.tf", "prod.tfstate.backup",
    "service-account-x.json", ".ssh", ".sshx", ".netrc", "_netrc", "app.mobileprovision",
]


@pytest.mark.parametrize("name", NAMES)
def test_protected_regexes_agree_with_the_workbench(name: str) -> None:
    for path in (f"/p/{name}", f"/p/{name}/inner.txt"):
        assert any(re.search(regex, path) for regex in sandbox.PROTECTED_REGEXES) == is_protected_name(name)


# --- What the script gets -------------------------------------------------------------


async def test_python_gets_stdin_folders_and_its_scratch(layout: Layout) -> None:
    script = (
        "import json, os, sys\n"
        "data = json.load(sys.stdin)\n"
        "open('out.txt', 'w').write('kept')\n"
        "print(json.dumps({'data': data, 'folders': json.loads(os.environ['FOLDERS']), 'cwd': os.getcwd(),\n"
        "  'home': os.environ['HOME'], 'tmp': os.environ['TMPDIR'], 'names': sorted(os.environ)}))\n"
    )
    folders = json.dumps({"shop": str(layout.project)})
    result = await layout.run("python", script, stdin=b'{"n": 3}', env={"FOLDERS": folders})
    assert result.exit_code == 0, result.output
    seen = json.loads(result.output)
    assert seen["data"] == {"n": 3}
    assert seen["folders"] == {"shop": str(layout.project)}
    assert seen["cwd"] == seen["home"] == seen["tmp"] == str(layout.scratch)
    assert not [name for name in seen["names"] if "KEY" in name or name.startswith("VISION")]
    assert (layout.scratch / "out.txt").read_text() == "kept"
    assert result.swept == 0 and not result.truncated


async def test_shell_gets_stdin_folders_and_its_scratch(layout: Layout) -> None:
    script = 'read -r line; echo "$line|$FOLDERS|$(pwd)"; echo kept > out.txt; ls /usr/bin/true'
    result = await layout.run("sh", script, stdin=b'{"n": 3}\n', env={"FOLDERS": "{}"})
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [f'{{"n": 3}}|{{}}|{layout.scratch}', "/usr/bin/true"]
    assert (layout.scratch / "out.txt").read_text() == "kept\n"


async def test_output_is_capped(layout: Layout) -> None:
    result = await layout.run("python", "print('x' * 5000)", limit=1000)
    assert result.truncated and len(result.output) == 1000


# --- Writing --------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["outside", "project"])
async def test_cannot_write_outside_its_scratch(layout: Layout, where: str) -> None:
    folder = layout.outside if where == "outside" else layout.project
    assert layout.free("python", write_script(folder / "free.txt")) == "WROTE\n"
    result = await layout.run("python", write_script(folder / "boxed.txt"), read=(layout.project,))
    assert result.output == f"{DENIED}\n"
    assert not (folder / "boxed.txt").exists()


async def test_shell_cannot_write_outside_its_scratch(layout: Layout) -> None:
    script = f"echo x > {layout.outside}/sh.txt && echo WROTE"
    assert layout.free("sh", script) == "WROTE\n"
    (layout.outside / "sh.txt").unlink()
    result = await layout.run("sh", script)
    assert "WROTE" not in result.output and "Operation not permitted" in result.output
    assert not (layout.outside / "sh.txt").exists()


async def test_each_file_it_writes_is_capped(layout: Layout, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "MAX_FILE_BYTES", 1024 * 1024)
    script = "open('big', 'wb').write(b'x' * (4 * 1024 * 1024))\nprint('WROTE')"
    assert layout.free("python", script) == "WROTE\n"
    (layout.scratch / "big").unlink()
    result = await layout.run("python", script)
    assert result.exit_code != 0 and "WROTE" not in result.output
    assert (layout.scratch / "big").stat().st_size <= 1024 * 1024


# --- Reading --------------------------------------------------------------------------


async def test_reads_only_what_it_was_given(layout: Layout) -> None:
    notes = layout.home / "notes.txt"
    assert layout.free("python", read_script(notes)) == "plain notes\n"
    assert (await layout.run("python", read_script(notes))).output == f"{DENIED}\n"
    assert (await layout.run("python", read_script(notes), read=(layout.home,))).output == "plain notes\n"


async def test_cannot_read_secret_folders_even_inside_an_approved_folder(layout: Layout) -> None:
    key = layout.home / ".ssh" / "id_rsa"
    assert layout.free("python", read_script(key)) == "PRIVATE KEY\n"
    result = await layout.run("python", read_script(key), read=(layout.home,))
    assert result.output == f"{DENIED}\n"
    listed = await layout.run("sh", f"ls {layout.home}/.ssh || echo {DENIED}", read=(layout.home,))
    assert DENIED in listed.output and "id_rsa" not in listed.output


async def test_cannot_read_the_assistants_home(layout: Layout) -> None:
    memory = layout.assistant / "memory.db"
    assert layout.free("python", read_script(memory)) == "the assistant's memory\n"
    result = await layout.run("python", read_script(memory), read=(layout.home,))
    assert result.output == f"{DENIED}\n"
    listed = await layout.run("sh", f"ls {layout.assistant} || echo {DENIED}", read=(layout.home,))
    assert DENIED in listed.output and "memory.db" not in listed.output


@pytest.mark.parametrize(
    ("name", "content"),
    [
        (".env", None),
        ("Deploy.PEM", None),
        ("secrets/notes.txt", None),
        (".env.example", "API_KEY="),
        ("readme.txt", "hello shop"),
    ],
)
async def test_protected_files_stay_closed_inside_an_approved_folder(
    layout: Layout, name: str, content: str | None
) -> None:
    path = layout.project / name
    assert layout.free("python", read_script(path)) != f"{DENIED}\n"
    result = await layout.run("python", read_script(path), read=(layout.project,))
    assert result.output == f"{content if content is not None else DENIED}\n"


async def test_protected_names_match_whatever_the_case(layout: Layout) -> None:
    result = await layout.run("python", read_script(layout.project / ".ENV"), read=(layout.project,))
    assert result.output == f"{DENIED}\n"


# --- Network and local sockets ----------------------------------------------------------


@contextlib.asynccontextmanager
async def tcp_server() -> AsyncIterator[int]:
    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"hello\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(answer, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


def connect_script(port: int) -> str:
    return (
        "import socket\n"
        "try:\n"
        f"    s = socket.create_connection(('127.0.0.1', {port}), timeout=5)\n"
        "    print(s.makefile().readline().strip())\n"
        f"except OSError:\n    print({DENIED!r})\n"
    )


async def test_network_is_closed_unless_approved(layout: Layout) -> None:
    async with tcp_server() as port:
        script = connect_script(port)
        assert await asyncio.to_thread(layout.free, "python", script) == "hello\n"
        closed = await layout.run("python", script)
        assert closed.output == f"{DENIED}\n"
        opened = await layout.run("python", script, network=True)
        assert opened.output == "hello\n"


@pytest.mark.parametrize("network", [False, True])
async def test_never_listens(layout: Layout, network: bool) -> None:
    script = (
        "import socket\n"
        "try:\n"
        "    s = socket.socket()\n    s.bind(('127.0.0.1', 0))\n    s.listen()\n    print('LISTENING')\n"
        f"except OSError:\n    print({DENIED!r})\n"
    )
    assert layout.free("python", script) == "LISTENING\n"
    assert (await layout.run("python", script, network=network)).output == f"{DENIED}\n"


@pytest.fixture
def unix_server() -> Iterator[Path]:
    # A socket path must be short (104 bytes), so it cannot live in tmp_path.
    folder = Path(os.path.realpath(tempfile.mkdtemp(prefix="vsb")))
    path = folder / "s"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen()
    try:
        yield path
    finally:
        server.close()
        shutil.rmtree(folder)


@pytest.mark.parametrize("network", [False, True])
async def test_cannot_connect_to_local_sockets(layout: Layout, unix_server: Path, network: bool) -> None:
    script = (
        "import socket\n"
        "try:\n"
        f"    socket.socket(socket.AF_UNIX).connect({str(unix_server)!r})\n    print('CONNECTED')\n"
        f"except OSError:\n    print({DENIED!r})\n"
    )
    assert layout.free("python", script) == "CONNECTED\n"
    result = await layout.run("python", script, read=(unix_server.parent,), network=network)
    assert result.output == f"{DENIED}\n"


# --- Time and leftovers -------------------------------------------------------------------


@pytest.mark.parametrize(("language", "script"), [("python", "while True:\n    pass"), ("sh", "while :; do :; done")])
async def test_stopped_at_the_timeout(layout: Layout, language: Language, script: str) -> None:
    started = time.monotonic()
    result = await layout.run(language, script, timeout=1.5)
    assert result.exit_code is None
    assert time.monotonic() - started < 6


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone_soon(pid: int) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


# A double fork with a new session: the grandchild leaves the process group
# and is adopted by launchd, so killing the run's group cannot reach it.
DETACH_PYTHON = """\
import os, time
ready, told = os.pipe()
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        null = os.open('/dev/null', os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        open('pid', 'w').write(str(os.getpid()))
        os.write(told, b'x')
        time.sleep(30)
    os._exit(0)
os.read(ready, 1)
print('LEFT')
"""

DETACH_SH = "( sleep 30 </dev/null >/dev/null 2>&1 & echo $! > pid ); echo LEFT"


@pytest.mark.parametrize(("language", "script"), [("python", DETACH_PYTHON), ("sh", DETACH_SH)])
async def test_leftover_processes_are_killed(layout: Layout, language: Language, script: str) -> None:
    assert layout.free(language, script) == "LEFT\n"
    control = int((layout.scratch / "pid").read_text())
    try:
        assert alive(control), "the control's detached process should outlive its run"
    finally:
        os.kill(control, 9)
    (layout.scratch / "pid").unlink()

    result = await layout.run(language, script)
    assert result.output == "LEFT\n" and result.exit_code == 0
    pid = int((layout.scratch / "pid").read_text())
    assert result.swept >= 1
    assert gone_soon(pid)


async def test_leftovers_are_killed_after_a_timeout(layout: Layout) -> None:
    script = DETACH_PYTHON + "while True:\n    pass\n"
    result = await layout.run("python", script, timeout=1.5)
    assert result.exit_code is None and result.swept >= 1
    assert gone_soon(int((layout.scratch / "pid").read_text()))


async def test_the_sweep_spares_other_processes(layout: Layout) -> None:
    bystander = await asyncio.create_subprocess_exec("/bin/sleep", "30")
    try:
        result = await layout.run("sh", "echo done")
        assert result.swept == 0
        assert bystander.returncode is None and alive(bystander.pid)
    finally:
        bystander.kill()
        await bystander.wait()
    assert not list(layout.scratch.parent.glob("run1.*")), "the marker files are removed after the run"
