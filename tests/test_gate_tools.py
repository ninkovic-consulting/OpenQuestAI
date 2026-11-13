from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vision.core.config import Config
from vision.gate.tools import CommandResult, Tool, ToolFailure, build_tools, run_command
from vision.testing.fakes import FakeMemory


class FakeRunner:
    def __init__(self, result: CommandResult = CommandResult(0, "", False)) -> None:
        self.result = result
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    async def __call__(self, argv: list[str], **kwargs: Any) -> CommandResult:
        self.calls.append((list(argv), kwargs))
        return self.result


def tools_by_name(config: Config, memory: FakeMemory, runner: FakeRunner) -> dict[str, Tool]:
    return {t.spec.name: t for t in build_tools(config, memory, runner=runner)}


@pytest.fixture
def memory() -> FakeMemory:
    return FakeMemory()


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


def test_specs_are_strict_objects(config: Config, memory: FakeMemory, runner: FakeRunner) -> None:
    for tool in build_tools(config, memory, runner=runner):
        schema = tool.spec.input_schema
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert schema["required"] == [tool.detail_arg]


async def test_remember_and_recall(config: Config, memory: FakeMemory, runner: FakeRunner) -> None:
    tools = tools_by_name(config, memory, runner)
    assert await tools["remember"].run({"text": "The release is on Friday"}) == "Noted."
    assert memory.notes[0][1] == "The release is on Friday"
    found = await tools["recall"].run({"query": "release"})
    assert found.startswith("- [note, ") and "release is on Friday" in found
    assert await tools["recall"].run({"query": "unrelated"}) == "Nothing found."
    with pytest.raises(ToolFailure):
        await tools["remember"].run({"text": "  "})


async def test_open_app(config: Config, memory: FakeMemory, runner: FakeRunner) -> None:
    tools = tools_by_name(config, memory, runner)
    assert await tools["open_app"].run({"name": "Calendar"}) == "Opened Calendar."
    assert runner.calls[0][0] == ["open", "-a", "Calendar"]
    with pytest.raises(ToolFailure):
        await tools["open_app"].run({"name": "--help"})
    runner.result = CommandResult(1, "Unable to find application named 'Nope'", False)
    with pytest.raises(ToolFailure, match="Unable to find"):
        await tools["open_app"].run({"name": "Nope"})


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "example.com"])
async def test_open_url_rejects_other_schemes(
    config: Config, memory: FakeMemory, runner: FakeRunner, url: str
) -> None:
    with pytest.raises(ToolFailure, match="http"):
        await tools_by_name(config, memory, runner)["open_url"].run({"url": url})
    assert runner.calls == []


async def test_open_url(config: Config, memory: FakeMemory, runner: FakeRunner) -> None:
    out = await tools_by_name(config, memory, runner)["open_url"].run({"url": "https://example.com/a?b=1"})
    assert out == "Opened https://example.com/a?b=1."
    assert runner.calls[0][0] == ["open", "https://example.com/a?b=1"]


def test_open_url_tells_the_model_it_only_shows_a_page_on_the_mac(
    config: Config, memory: FakeMemory, runner: FakeRunner
) -> None:
    tool = tools_by_name(config, memory, runner)["open_url"]
    text = tool.spec.description
    assert "on the Mac's screen" in text and "You cannot see or read the page" in text
    assert "Never use it to look something up" in text and "hand_off" in text
    assert "In a turn from the phone" in text
    assert tool.summary == "Open a link"


def test_shell_tells_the_model_it_asks_unless_made_free(
    config: Config, memory: FakeMemory, runner: FakeRunner
) -> None:
    text = tools_by_name(config, memory, runner)["shell"].spec.description
    assert "approves each command first, unless they have set shell to run freely" in text


async def test_shell_runs_with_limits(config: Config, memory: FakeMemory, runner: FakeRunner) -> None:
    config.gate.shell_timeout_s = 7  # type: ignore[attr-defined]
    runner.result = CommandResult(0, "hello\n", False)
    out = await tools_by_name(config, memory, runner)["shell"].run({"command": "echo hello"})
    assert out == "exit code 0\nhello"
    argv, kwargs = runner.calls[0]
    assert argv == ["/bin/sh", "-c", "echo hello"]
    assert kwargs["timeout"] == 7 and kwargs["limit"] == 8000 and kwargs["cwd"] == Path.home()


async def test_shell_failure_timeout_and_truncation(
    config: Config, memory: FakeMemory, runner: FakeRunner
) -> None:
    shell = tools_by_name(config, memory, runner)["shell"]
    runner.result = CommandResult(2, "boom", False)
    with pytest.raises(ToolFailure, match="exit code 2\nboom"):
        await shell.run({"command": "false"})
    runner.result = CommandResult(None, "partial", False)
    with pytest.raises(ToolFailure, match="did not finish within 30 seconds"):
        await shell.run({"command": "sleep 100"})
    runner.result = CommandResult(0, "x" * 10, True)
    assert (await shell.run({"command": "yes"})).endswith("[output truncated]")


# ------------------------------------------------------------ the real runner, harmless commands only


async def test_run_command_captures_output_and_exit_code() -> None:
    result = await run_command(["/bin/sh", "-c", "echo out; echo err >&2; exit 3"], timeout=5, limit=100)
    assert result.returncode == 3
    assert "out" in result.output and "err" in result.output and not result.truncated


async def test_run_command_caps_output() -> None:
    result = await run_command(["/bin/sh", "-c", "head -c 5000 /dev/zero"], timeout=5, limit=100)
    assert result.returncode == 0 and len(result.output) == 100 and result.truncated


async def test_run_command_stops_at_timeout() -> None:
    result = await run_command(["/bin/sh", "-c", "echo started; sleep 10"], timeout=0.3, limit=100)
    assert result.returncode is None and "started" in result.output
