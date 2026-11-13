"""The residents at work: each job runs as the resident's own session.

`Residents` is the board's `Work`. For a job it

- picks the model: the room's (the plan resolves a room's own model over its
  agent's) when the room is the resident's own, else the agent's own model,
  so a visitor brings its own; the agent's `heavy_model` when the job is
  careful and it has one;
- gathers the tools (`abilities`): the resident's own notes, `note_progress`,
  `ask_resident` (not in a request from another resident), the steward's
  and the scout's extras, and the project tools of the room the job runs in
  (its own or another agent's) when that room's project folder exists. Nothing the host alone may do is ever among them;
- puts them behind a gate scoped to the job (same tiers, audit and bus; the
  card names the agent and its room);
- writes the system prompt (`prompt`) and runs the loop (`worker`).

The SDK client, the gate scope and the workbench's project tools are
injected by the composition root, so the tests run on fakes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from vision.aware.personas import Personas
from vision.core.config import Config
from vision.core.interfaces import Budget
from vision.core.localtime import local_zone
from vision.core.programs import find_program
from vision.gate.gate import Actor, JobHooks, ToolGate
from vision.gate.tools import Tool
from vision.house.tools import load_catalog
from vision.jobs import Desk, Job, Outcome
from vision.residents import abilities, prompt
from vision.residents.machine import MacProbe, Probe
from vision.residents.notes import ResidentNotes
from vision.residents.project import ProjectTools, load_project_tools
from vision.residents.tools import machine_tool, own_tools
from vision.residents.worker import ClientSource, Session, web_search_tool, work

Scope = Callable[[Sequence[Tool], Actor, JobHooks], ToolGate]
Finder = Callable[[str], Path | None]

NO_KEY = "No Anthropic API key is stored, and the residents work only on Claude."

__all__ = ["Residents", "Scope", "load_project_tools"]


class Residents:
    def __init__(
        self,
        config: Config,
        *,
        plan: Callable[[], dict[str, Any]],
        budget: Callable[[], Budget],
        client: ClientSource,
        scope: Scope,
        host_tools: Mapping[str, Tool],
        project_tools: ProjectTools | None,
        probe: Probe | None = None,
        finder: Finder = find_program,
    ) -> None:
        self._config = config
        self._plan = plan
        self._budget = budget
        self._client = client
        self._scope = scope
        self._host_tools = host_tools
        self._project_tools = project_tools
        self._probe = probe or MacProbe()
        self._finder = finder
        self._personas = Personas(config.paths.house)

    @property
    def has_project_tools(self) -> bool:
        return self._project_tools is not None

    async def __call__(self, job: Job, desk: Desk) -> Outcome:
        plan = self._plan()
        agent = next(a for a in plan["agents"] if a["id"] == job.agent)
        room = next((r for r in plan["rooms"] if r["id"] == job.room), None)
        own_room = room is not None and room["agent"] == agent["id"]
        model = room["model"] if own_room and room is not None else agent["model"]
        if job.careful and agent.get("heavy_model"):
            model = agent["heavy_model"]
        project = _folder(room)
        notes = ResidentNotes(self._config.paths.house, agent["id"])
        tools, refused = self._tools(agent["id"], job, desk, notes, room, project)
        if refused:
            desk.step("progress", f"Working without project tools: {refused}")
            project = None
        actor = Actor(agent["id"], agent["name"], job.id, room["name"] if room else None)
        gate = self._scope(tools, actor, desk)
        server: list[dict[str, Any]] = []
        if "web_search" in abilities.extra(agent["id"]) and await gate.permit(
            "web_search", "Search the web", job.title
        ):
            server.append(web_search_tool(model, self._config.jobs.web_search_max_uses))
        names = [t.spec.name for t in tools] + [s["name"] for s in server]
        owner = next((a["name"] for a in plan["agents"] if room and a["id"] == room["agent"]), "")
        setting = prompt.Setting(agent, room, project, refused, owner)
        system = await asyncio.to_thread(self._system, plan, setting, names, notes)
        client = await self._client()
        if client is None:
            return Outcome("failed", "", NO_KEY)
        asker = desk.board.agent_name(job.asked_by)
        session = Session(
            model=model,
            careful=job.careful,
            system=system,
            opening=prompt.opening(job, asker, datetime.now(local_zone())),
            server_tools=server,
            max_steps=self._config.jobs.max_steps,
            max_job_usd=self._config.jobs.max_job_usd,
        )
        return await work(client, gate, desk, self._budget(), session)

    def _tools(
        self,
        agent: str,
        job: Job,
        desk: Desk,
        notes: ResidentNotes,
        room: dict[str, Any] | None,
        project: Path | None,
    ) -> tuple[list[Tool], str | None]:
        """The job's tools, and why the project tools were left out when the workbench refused
        the folder (`/`, the home folder or one above it)."""
        tools = own_tools(notes, desk, may_ask=job.parent is None)
        refused: str | None = None
        for name in abilities.extra(agent):
            if name == "machine_status":
                tools.append(machine_tool(self._probe))
            elif name in self._host_tools:
                tools.append(self._host_tools[name])
        if project is not None and room is not None and self._project_tools is not None:
            try:
                tools += self._project_tools(project, self._programs(room))
            except ValueError as exc:
                refused = str(exc) or "the folder cannot be a project folder"
        return [t for t in tools if t.spec.name not in abilities.HOST_ONLY], refused

    def _programs(self, room: dict[str, Any]) -> dict[str, Path]:
        """The room's project tools that are installed, by catalog id, with their program's path."""
        catalog = load_catalog()
        found: dict[str, Path] = {}
        for ref in room["tools"]:
            info = catalog.get(ref["id"])
            if info is None or info.built_in or info.program is None:
                continue
            path = self._finder(info.program)
            if path is not None:
                found[info.id] = path
        return found

    def _system(self, plan: dict[str, Any], setting: prompt.Setting, names: list[str], notes: ResidentNotes) -> str:
        persona_file = setting.agent.get("persona")
        persona = ""
        if isinstance(persona_file, str) and persona_file:
            try:
                persona = (self._config.paths.house / persona_file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                persona = ""
        return prompt.system_prompt(
            persona=persona,
            plan=plan,
            personas=self._personas,
            setting=setting,
            tools=names,
            library_text=prompt.library(self._config.paths.house),
            notes=notes.recent(prompt.NOTES_CHARS),
        )


def _folder(room: dict[str, Any] | None) -> Path | None:
    project = room.get("project") if room else None
    if not isinstance(project, str) or not project:
        return None
    path = Path(project).expanduser()
    return path if path.is_dir() else None
