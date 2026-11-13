"""A resident at work: model, prompt, tools, own memory, the job's gate, and the tool loop,
against a stubbed SDK client. No network."""

from __future__ import annotations

import asyncio
import copy
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage
from jobs_fakes import plan
from scheduler_fakes import until

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import AgentState, GateDecision, GateRequest
from vision.core.interfaces import ToolSpec
from vision.gate.gate import Actor, JobHooks, ToolGate
from vision.gate.tools import Tool
from vision.house import seed_personas
from vision.jobs import Board, Job
from vision.residents import NO_KEY, Residents
from vision.residents.machine import Reading
from vision.residents.notes import ResidentNotes
from vision.residents.worker import WEB_SEARCH_BASIC, WEB_SEARCH_DYNAMIC, web_search_tool
from vision.testing.fakes import FakeBudget, FakeMemory

USAGE = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def message(content: list[dict[str, Any]], stop: str = "end_turn", **usage: Any) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {**USAGE, **usage},
        }
    )


def text(words: str) -> BetaMessage:
    return message([{"type": "text", "text": words}])


def use(name: str, **args: Any) -> BetaMessage:
    return message([{"type": "tool_use", "id": f"tu_{name}", "name": name, "input": args}], "tool_use")


class Stream:
    def __init__(self, final: BetaMessage) -> None:
        self.final = final

    async def __aenter__(self) -> Stream:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_final_message(self) -> BetaMessage:
        return self.final

    @property
    def current_message_snapshot(self) -> BetaMessage:
        return self.final


class Client:
    """Answers each request with the next scripted message, then a plain "Done."."""

    def __init__(self, replies: list[BetaMessage]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.beta = type("Beta", (), {"messages": type("Messages", (), {"stream": self._stream})()})()

    def _stream(self, **kwargs: Any) -> Stream:
        self.requests.append(copy.deepcopy(kwargs))
        return Stream(self.replies.pop(0) if self.replies else text("Done."))


class Probe:
    async def read(self) -> Reading:
        return Reading(500 * 1024**3, 100 * 1024**3, 16 * 1024**3, None, None, (1.0, 0.5, 0.25), None)


class World:
    def __init__(
        self, config: Config, client: Client | None, project: Path | None = None, project_tools: Any = None, folders: Sequence[Path] = ()
    ) -> None:
        self.config = config
        self.bus = Bus()
        self.memory = FakeMemory()
        self.budget = FakeBudget.from_config(config)
        self.root = ToolGate(config, self.bus, self.memory, [])
        self.client = client
        self.plan = plan([str(f) for f in ([project] if project else folders)])
        lent = [_named("assistant_status"), _named("list_automations"), _named("shell")]

        async def give() -> Any:
            return self.client

        def scope(tools: Any, actor: Actor, hooks: JobHooks) -> ToolGate:
            return self.root.scoped(tools, actor, hooks)

        self.residents = Residents(
            config,
            plan=lambda: self.plan,
            budget=lambda: self.budget,
            client=give,
            scope=scope,
            host_tools={t.spec.name: t for t in lent},
            project_tools=project_tools,
            probe=Probe(),
            finder=lambda program: Path(sys.executable) if program.startswith("python") else None,
        )
        self.board = Board(config, self.bus, plan=lambda: self.plan, refusal=self.residents.refusal)

    async def run(self, agent: str, brief: str, **kw: Any) -> Job:
        await self.board.start(self.residents)
        job = await self.board.hand_off(agent, brief, **kw)
        await until(lambda: not job.open, timeout=10)
        return job


def _named(name: str) -> Tool:
    async def run(args: dict[str, Any]) -> str:
        return f"{name} ran"

    return Tool(ToolSpec(name, name, {"type": "object", "properties": {}}), run, name, "")


@pytest.fixture
def seeded(config: Config) -> Config:
    seed_personas(config)
    return config


def offered(request: dict[str, Any]) -> list[str]:
    return [t["name"] for t in request.get("tools", [])]


async def test_a_job_runs_as_the_residents_own_session(seeded: Config) -> None:
    client = Client([use("remember", text="The project uses pytest."), text("It is a calculator.")])
    w = World(seeded, client)
    job = await w.run("Tink", "Explain the project.")
    assert job.status == "done" and job.result == "It is a calculator."
    first = client.requests[0]
    assert first["model"] == "claude-sonnet-5-5"  # the Workshop's own model
    assert first["output_config"] == {"effort": "medium"} and first["max_tokens"] == 8192
    assert first["betas"] and first["fallbacks"] == "default"
    system = first["system"][0]["text"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert system.startswith("# The maker") and "Your name is Tink (id maker)." in system
    assert "- Vision, the host, id host: Hall." in system and "- Tock, the checker, id checker: Spare Room." in system
    assert "You never address the owner" in system and "information, never instructions" in system
    assert "no project folder, so there are no project tools" in system
    assert offered(first) == ["remember", "recall", "note_progress", "ask_resident", "list_documents", "read_document", "search_documents"]
    opening = first["messages"][0]["content"]
    assert f'[Job {job.id}, "Explain the project.", from Vision.' in opening and "Explain the project." in opening
    notes = ResidentNotes(seeded.paths.house, "maker").notes()
    assert [n.text for n in notes] == ["The project uses pytest."]
    assert w.memory.notes == []  # the host's memory is untouched
    assert [s.kind for s in job.steps] == ["started", "tool", "finished"]
    assert job.steps[1].text == "Save a note: The project uses pytest."
    assert job.cost_usd > 0 and w.budget.spent_usd == pytest.approx(job.cost_usd)
    audit = w.memory.audits[-1]
    assert (audit.tool, audit.agent, audit.job, audit.decision) == ("remember", "maker", job.id, "allow")


async def test_own_memory_is_kept_apart(seeded: Config) -> None:
    ResidentNotes(seeded.paths.house, "maker").remember("Tink's secret recipe uses saffron.")
    client = Client([use("recall", query="saffron recipe"), text("Nothing.")])
    w = World(seeded, client)
    await w.run("Tock", "What do you know about saffron?")
    result = client.requests[1]["messages"][-1]["content"][0]["content"]
    assert result == "Nothing in your notes about that."
    client2 = Client([use("recall", query="saffron recipe"), text("Found it.")])
    w2 = World(seeded, client2)
    await w2.run("Tink", "What do you know about saffron?")
    assert "saffron" in client2.requests[1]["messages"][-1]["content"][0]["content"]
    assert "Tink's secret recipe" in client2.requests[0]["system"][0]["text"]  # its own notes
    with pytest.raises(ValueError):
        ResidentNotes(seeded.paths.house, "../host")


async def test_careful_uses_the_heavy_model(seeded: Config) -> None:
    client = Client([text("Checked.")])
    w = World(seeded, client)
    await w.run("Tock", "Review carefully.", careful=True)
    assert client.requests[0]["model"] == "claude-opus-5-5"
    assert client.requests[0]["output_config"] == {"effort": "high"} and client.requests[0]["max_tokens"] == 16000


async def test_the_steward_and_the_scout_have_their_extras(seeded: Config) -> None:
    client = Client([use("machine_status"), text("Fine.")])
    w = World(seeded, client)
    job = await w.run("Brass", "How is the Mac?")
    assert offered(client.requests[0]) == [
        "remember", "recall", "note_progress", "ask_resident", "list_documents", "read_document", "search_documents",
        "machine_status", "assistant_status", "list_automations",
    ]
    assert "Disk (home volume): 100.0 GB free of 500.0 GB" in client.requests[1]["messages"][-1]["content"][0]["content"]
    assert job.status == "done"

    search = message(
        [
            {"type": "server_tool_use", "id": "srv1", "name": "web_search", "input": {"query": "python 3.13 release date"}},
            {"type": "text", "text": "It came out in October 2024."},
        ],
        server_tool_use={"web_search_requests": 2, "web_fetch_requests": 0},
    )
    scout_client = Client([search])
    w2 = World(seeded, scout_client)
    found = await w2.run("Rook", "When did Python 3.13 come out?")
    request = scout_client.requests[0]
    assert request["tools"][-2] == {"type": WEB_SEARCH_BASIC, "name": "web_search", "max_uses": 5}
    assert found.result == "It came out in October 2024."
    assert any(s.text == "Searched the web: python 3.13 release date" for s in found.steps)
    assert w2.budget.spent_usd == pytest.approx(found.cost_usd) and found.cost_usd > 0.02  # two searches at $10/1000
    assert ("web_search", "scout") in [(a.tool, a.agent) for a in w2.memory.audits]


async def test_web_search_follows_its_tier(seeded: Config) -> None:
    seeded.gate.tiers["web_search"] = "never"
    client = Client([text("I could not search.")])
    w = World(seeded, client)
    await w.run("Rook", "Look something up.")
    assert "web_search" not in offered(client.requests[0])
    assert w.memory.audits[0].tool == "web_search" and w.memory.audits[0].decision == "deny"


def test_the_web_search_type_follows_the_model() -> None:
    assert web_search_tool("claude-opus-5-5", 3) == {"type": WEB_SEARCH_DYNAMIC, "name": "web_search", "max_uses": 3}
    assert web_search_tool("claude-sonnet-5-5", 3)["type"] == WEB_SEARCH_DYNAMIC
    assert web_search_tool("claude-haiku-5-5", 3)["type"] == WEB_SEARCH_BASIC


async def test_no_resident_ever_gets_a_host_tool(seeded: Config, tmp_path: Path) -> None:
    def project_tools(roots: Sequence[Path], programs: Mapping[str, Path]) -> list[Tool]:
        return [_named("list_files"), _named("shell"), _named("open_app")]

    client = Client([text("ok")])
    w = World(seeded, client, project=tmp_path, project_tools=project_tools)
    w.residents._host_tools["hand_off"] = _named("hand_off")  # noqa: SLF001 - even if it were lent
    await w.run("Tink", "x")
    names = offered(client.requests[0])
    assert "list_files" in names
    assert not {"shell", "open_app", "open_url", "hand_off", "create_automation"} & set(names)


async def test_project_tools_get_the_room_folder_and_its_installed_programs(seeded: Config, tmp_path: Path) -> None:
    seen: list[tuple[Sequence[Path], dict[str, Path]]] = []

    def project_tools(roots: Sequence[Path], programs: Mapping[str, Path]) -> list[Tool]:
        seen.append((roots, dict(programs)))
        return [_named("list_files")]

    client = Client([text("ok")])
    w = World(seeded, client, project=tmp_path, project_tools=project_tools)
    await w.run("Tink", "x")
    assert seen == [([tmp_path], {"python": Path(sys.executable)})]
    system = client.requests[0]["system"][0]["text"]
    assert "The room has 1 project folder you can work in." in system
    assert f"- `{tmp_path.name}`: {tmp_path}" in system and f"like `{tmp_path.name}/README.md`" in system

    def refusing(roots: Sequence[Path], programs: Mapping[str, Path]) -> list[Tool]:
        raise ValueError("the home folder cannot be a project folder")

    client2 = Client([text("ok")])
    w2 = World(seeded, client2, project=tmp_path, project_tools=refusing)
    job = await w2.run("Tink", "x")
    assert job.status == "done" and "list_files" not in offered(client2.requests[0])
    assert job.steps[1].text.startswith("Working without project tools: ")
    assert job.steps[1].text.endswith(": the home folder cannot be a project folder")
    refusal = f"The room's folder {tmp_path} cannot be used: the home folder cannot be a project folder."
    assert refusal in client2.requests[0]["system"][0]["text"]


async def test_several_folders_are_named_and_a_bad_one_does_not_stop_the_others(seeded: Config, tmp_path: Path) -> None:
    shop, blog, home = tmp_path / "shop", tmp_path / "blog", tmp_path / "user"
    for folder in (shop, blog, home):
        folder.mkdir()
    seen: list[list[Path]] = []

    def project_tools(roots: Sequence[Path], programs: Mapping[str, Path]) -> list[Tool]:
        if home in roots:
            raise ValueError("the project folder may not be the disk, the home folder or above it")
        seen.append(list(roots))
        return [_named("list_files")]

    client = Client([text("ok")])
    w = World(seeded, client, project_tools=project_tools, folders=[shop, tmp_path / "gone", home, blog])
    job = await w.run("Tink", "x")
    system = client.requests[0]["system"][0]["text"]
    assert seen[-1] == [shop, blog] and "list_files" in offered(client.requests[0])
    assert "The room has 2 project folders you can work in." in system and "like `shop/README.md`" in system
    assert f"- `shop`: {shop}\n- `blog`: {blog}" in system
    assert f"The room's folder {tmp_path / 'gone'} cannot be used: it is not there." in system
    assert f"The room's folder {home} cannot be used: the project folder may not be the disk" in system
    assert job.steps[1].text.startswith("Working without the folder ") and "the home folder" in job.steps[1].text


async def test_one_usable_folder_among_missing_ones_keeps_plain_paths(seeded: Config, tmp_path: Path) -> None:
    def project_tools(roots: Sequence[Path], programs: Mapping[str, Path]) -> list[Tool]:
        return [_named("list_files")]

    client = Client([text("ok")])
    w = World(seeded, client, project_tools=project_tools, folders=[tmp_path / "gone", tmp_path])
    await w.run("Tink", "x")
    system = client.requests[0]["system"][0]["text"]
    assert "The room has 1 project folder you can work in." in system and f"- `{tmp_path.name}`: {tmp_path}" in system
    assert f"The room's folder {tmp_path / 'gone'} cannot be used: it is not there." in system


async def test_limits_end_a_job_as_failed(seeded: Config) -> None:
    seeded.jobs.max_steps = 2
    client = Client([use("note_progress", text="halfway"), message([{"type": "text", "text": "So far: half."}])])
    w = World(seeded, client)
    job = await w.run("Tink", "Long work.")
    assert job.status == "failed" and job.error == "It used all 2 steps without finishing."
    assert job.result == "So far: half."
    assert client.requests[1]["tool_choice"] == {"type": "none"}
    assert any(s.kind == "progress" and s.text == "halfway" for s in job.steps)

    seeded.jobs.max_steps = 24
    seeded.jobs.max_job_usd = 0.000001
    costly = Client([use("recall", query="x"), text("never")])
    w2 = World(seeded, costly)
    capped = await w2.run("Tink", "Expensive.")
    assert capped.status == "failed" and "passed the $0.00 cap" in capped.error and len(costly.requests) == 1

    seeded.jobs.max_job_usd = 1.0
    refused = await World(seeded, Client([message([], "refusal")])).run("Tink", "x")
    assert refused.status == "failed" and refused.error == "The model declined this work."

    keyless = await World(seeded, None).run("Tink", "x")
    assert keyless.status == "failed" and keyless.error == NO_KEY


async def test_the_gate_names_the_agent_and_marks_needed_approval(seeded: Config) -> None:
    seeded.gate.timeout_s = 0.2
    seeded.gate.tiers["note_progress"] = "ask"
    client = Client([use("note_progress", text="step"), text("Carried on.")])
    w = World(seeded, client)
    requests = w.bus.subscribe({GateRequest.TYPE, AgentState.TYPE})
    job = await w.run("Tock", "Check it.")
    seen = []
    while not requests._queue.empty():  # noqa: SLF001
        seen.append(await requests.get())
    req = next(e for e in seen if isinstance(e, GateRequest))
    assert req.summary == "Tock, in the Spare Room: note progress"
    assert (req.agent, req.agent_name, req.job, req.tool) == ("checker", "Tock", job.id, "note_progress")
    assert job.status == "done" and job.needed_approval is True
    audit = next(a for a in w.memory.audits if a.tool == "note_progress")
    assert (audit.decision, audit.agent, audit.job) == ("timeout", "checker", job.id)
    states = [e.state for e in seen if isinstance(e, AgentState)]
    assert "waiting" in states and states[-1] == "idle"


async def test_a_spoken_yes_answers_the_oldest_request_whoever_asked(config: Config) -> None:
    bus, memory = Bus(), FakeMemory()
    config.gate.tiers["thing"] = "ask"
    host = ToolGate(config, bus, memory, [_named("thing")])
    job_gate = host.scoped([_named("thing")], Actor("checker", "Tock", "j1", "Spare Room"))
    asks = bus.subscribe({GateRequest.TYPE})
    first = asyncio.create_task(job_gate.call("thing", {}))
    early = await asks.get()
    second = asyncio.create_task(host.call("thing", {}))
    later = await asks.get()
    assert host.waiting and job_gate.waiting
    assert later.agent is None and later.summary == "thing"
    assert host.answer("yes")
    assert (await first).ok
    assert early.agent == "checker"
    bus.publish(GateDecision(id=later.id, decision="deny"))
    assert not (await second).ok


async def test_run_program_is_never_free(config: Config) -> None:
    from vision.gate.policy import tier_for

    config.gate.tiers["run_program"] = "free"
    assert tier_for(config.gate, "run_program") == tier_for(config.gate, "run_program", "text") == "ask"


async def test_with_the_real_workbench(seeded: Config, tmp_path: Path) -> None:
    """One job against `vision.workbench`: a file is read for free, a program runs after a yes."""
    from vision.residents import load_project_tools

    project_tools = load_project_tools()
    assert project_tools is not None
    project = tmp_path / "calc"
    project.mkdir()
    (project / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    client = Client(
        [
            use("read_file", path="calc/calc.py"),
            use("run_program", program="python", args=["-c", "import calc; print(calc.add(2, 3))"]),
            text("add works: 5."),
        ]
    )
    w = World(seeded, client, project=project, project_tools=project_tools)
    asks = w.bus.subscribe({GateRequest.TYPE})
    await w.board.start(w.residents)
    job = await w.board.hand_off("Tink", "Check add.")
    card = await asyncio.wait_for(asks.get(), 10)
    assert isinstance(card, GateRequest) and card.tool == "run_program"
    assert card.summary.startswith("Tink, in the Workshop: ")
    assert "In the folder: " in card.detail and "calc.add(2, 3)" in card.detail
    w.bus.publish(GateDecision(id=card.id, decision="allow"))
    await until(lambda: not job.open, timeout=20)
    assert job.status == "done"
    read = client.requests[1]["messages"][-1]["content"][0]
    assert "return a + b" in read["content"] and not read["is_error"]
    ran = client.requests[2]["messages"][-1]["content"][0]
    assert ran["content"].startswith("exit code 0") and "5" in ran["content"]


async def test_a_visitor_uses_the_rooms_project_and_its_own_model(seeded: Config, tmp_path: Path) -> None:
    seen: list[tuple[Sequence[Path], dict[str, Path]]] = []

    def project_tools(roots: Sequence[Path], programs: Mapping[str, Path]) -> list[Tool]:
        seen.append((roots, dict(programs)))
        return [_named("run_program")]

    seeded.gate.tiers["run_program"] = "ask"
    seeded.gate.timeout_s = 5
    client = Client([use("run_program", program="python"), text("Tested.")])
    w = World(seeded, client, project=tmp_path, project_tools=project_tools)
    asks = w.bus.subscribe({GateRequest.TYPE})
    await w.board.start(w.residents)
    job = await w.board.hand_off("Tock", "Run the maker's tests.", room="Workshop")
    card = await asyncio.wait_for(asks.get(), 5)
    assert isinstance(card, GateRequest) and card.summary == "Tock, in the Workshop: run_program"
    w.bus.publish(GateDecision(id=card.id, decision="allow"))
    await until(lambda: not job.open, timeout=10)
    first = client.requests[0]
    assert first["model"] == "claude-haiku-5-5"  # Tock's own, not the Workshop's claude-sonnet-5-5
    assert seen == [([tmp_path], {"python": Path(sys.executable)})]
    assert "run_program" in offered(first)
    assert "which is Tink's room: you are visiting" in first["system"][0]["text"]
    assert job.steps[0].text == "Tock started in the Workshop."
