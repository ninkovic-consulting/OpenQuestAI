"""The residents at work: each job runs as the resident's own session.

`Residents` is the board's `Work`. For a job it

- picks the model: the room's (the plan resolves a room's own model over its
  agent's) when the room is the resident's own, else the agent's own model,
  so a visitor brings its own; the agent's `heavy_model` when the job is
  careful and it has one; and the thinking effort, the agent's `effort` (its
  `heavy_effort` when careful), lowered to the nearest level that model takes;
- gathers the tools (`abilities`): the resident's own notes, `note_progress`,
  `ask_resident` (not in a request from another resident), the steward's
  and the scout's extras, and the project tools of the room the job runs in
  (its own or another agent's) over those of its project folders that exist
  and the workbench accepts; a folder that cannot be used is named, with the
  reason, and the others still work. Nothing the host alone may do is ever
  among them;
- puts them behind a gate scoped to the job (same tiers, audit and bus; the
  card names the agent and its room);
- writes the system prompt (`prompt`) and runs the loop: on Claude
  (`worker`), or on the local model (`local_worker`) in offline mode, and
  when Claude cannot be used for the job (no API key, or the month's budget
  used up) while the local model is on disk and can call tools. The job
  records which model it runs on.

The SDK client, the local engine, the gate scope and the workbench's project
tools are injected by the composition root, so the tests run on fakes.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from vision.aware.personas import Personas
from vision.brains.engine import LocalEngine
from vision.brains.local_errors import LocalModelError
from vision.core import effort
from vision.core.config import Config
from vision.core.interfaces import Budget
from vision.core.folders import folder_names
from vision.core.localtime import local_zone
from vision.core.programs import find_program
from vision.gate.gate import Actor, JobHooks, ToolGate
from vision.gate.tools import Tool
from vision.house.tools import load_catalog
from vision.jobs import Desk, Job, Outcome
from vision.memory import resident_knowledge, resident_tools
from vision.residents import abilities, prompt
from vision.residents.machine import MacProbe, Probe
from vision.residents.notes import ResidentNotes
from vision.residents.project import ProjectTools, load_project_tools
from vision.residents.tools import machine_tool, own_tools
from vision.residents.local_worker import LocalSession, work_local
from vision.residents.worker import ClientSource, Session, web_fetch_tool, web_search_tool, work

Scope = Callable[[Sequence[Tool], Actor, JobHooks], ToolGate]
Finder = Callable[[str], Path | None]

NO_KEY = (
    "No Anthropic API key is stored, and the local model cannot take the work (it is not downloaded "
    "or cannot use tools)."
)
BUDGET_USED = (
    "This month's API budget is used up, and the local model cannot take the work (it is not "
    "downloaded or cannot use tools), so nobody can take work until the month turns or the cap is "
    "raised in Settings."
)

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
        local: LocalEngine | None = None,
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
        self._local = local
        self._probe = probe or MacProbe()
        self._finder = finder
        self._personas = Personas(config.paths.house)

    @property
    def has_project_tools(self) -> bool:
        return self._project_tools is not None

    async def local_problem(self) -> str | None:
        """Why the local model cannot take a resident's job now, or None when it can."""
        engine = self._local
        if engine is None:
            return "There is no local model in this build."
        try:
            missing = await engine.ready()
            if missing is not None:
                return missing
            if not await engine.can_call_tools():
                return (
                    f"The local model {engine.model} cannot use tools, so the residents cannot work on "
                    "it. Choose one that can in Settings, under Models."
                )
        except LocalModelError as exc:
            return exc.error.message
        return None

    async def refusal(self) -> str | None:
        """Why no resident can take work now (the board refuses a hand-off), or None."""
        if self._config.brain.offline:
            problem = await self.local_problem()
            return f"Offline mode is on and the residents work on the local model. {problem}" if problem else None
        if self._budget().exhausted() and await self.local_problem() is not None:
            return BUDGET_USED
        return None

    async def __call__(self, job: Job, desk: Desk) -> Outcome:
        plan = self._plan()
        agent = next(a for a in plan["agents"] if a["id"] == job.agent)
        room = next((r for r in plan["rooms"] if r["id"] == job.room), None)
        own_room = room is not None and room["agent"] == agent["id"]
        model = room["model"] if own_room and room is not None else agent["model"]
        if job.careful and agent.get("heavy_model"):
            model = agent["heavy_model"]
        offline = self._config.brain.offline
        client = None if offline else await self._client()
        local = offline or (
            (client is None or self._budget().exhausted()) and await self.local_problem() is None
        )
        if client is None and not local:
            return Outcome("failed", "", NO_KEY)
        if local and self._local is not None:
            desk.using(self._local.model, local=True)
        else:
            desk.using(model, local=False)
        notes = ResidentNotes(self._config.paths.house, agent["id"])
        tools, folders = self._tools(agent["id"], job, desk, notes, room, _folders(room))
        actor = Actor(agent["id"], agent["name"], job.id, room["name"] if room else None)
        gate = self._scope(tools, actor, desk)
        server: list[dict[str, Any]] = []
        uses = self._config.jobs
        for name, summary, make, most in (
            ("web_search", "Search the web", web_search_tool, uses.web_search_max_uses),
            ("web_fetch", "Load web pages", web_fetch_tool, uses.web_fetch_max_uses),
        ):
            if not local and name in abilities.extra(agent["id"]) and await gate.permit(name, summary, job.title):
                server.append(make(model, most))
        names = [t.spec.name for t in tools] + [s["name"] for s in server]
        owner = next((a["name"] for a in plan["agents"] if room and a["id"] == room["agent"]), "")
        setting = prompt.Setting(agent, room, folders, owner)
        system = await asyncio.to_thread(self._system, plan, setting, names, notes)
        asker = desk.board.agent_name(job.asked_by)
        opening = prompt.opening(job, asker, datetime.now(local_zone()))
        if local:
            if self._local is None:
                return Outcome("failed", "", "There is no local model in this build.")
            problem = await self.local_problem()
            if problem is not None:
                return Outcome("failed", "", problem)
            on_local = LocalSession(system, opening, job.careful, self._config.jobs.max_steps, offline)
            return await work_local(self._local, gate, desk, on_local)
        session = Session(
            model=model,
            careful=job.careful,
            system=system,
            opening=opening,
            server_tools=server,
            max_steps=self._config.jobs.max_steps,
            max_job_usd=self._config.jobs.max_job_usd,
            effort=effort.usable(model, _level(agent, job.careful)),
            offline=lambda: self._config.brain.offline,
        )
        return await work(client, gate, desk, self._budget(), session)

    def _tools(
        self,
        agent: str,
        job: Job,
        desk: Desk,
        notes: ResidentNotes,
        room: dict[str, Any] | None,
        folders: list[prompt.Folder],
    ) -> tuple[list[Tool], tuple[prompt.Folder, ...]]:
        """The job's tools, and the room's folders as the job may use them: a missing one, or
        one the workbench refuses (`/`, the home folder or above it), carries the reason, and
        the usable ones carry the short names their paths start with."""
        tools = own_tools(notes, desk, may_ask=job.parent is None)
        tools += resident_tools(self._config.paths.house)
        for name in abilities.extra(agent):
            if name == "machine_status":
                tools.append(machine_tool(self._probe))
            elif name in self._host_tools:
                tools.append(self._host_tools[name])
        if room is not None and self._project_tools is not None and _usable(folders):
            programs = self._programs(room)
            try:
                tools += self._project_tools([f.path for f in _usable(folders)], programs)
            except ValueError as exc:
                folders = self._refusals(folders, exc)
                try:
                    if _usable(folders):
                        tools += self._project_tools([f.path for f in _usable(folders)], programs)
                except ValueError as again:
                    folders = [f if f.problem else dataclasses.replace(f, problem=_reason(again)) for f in folders]
            self._report_refused(desk, folders)
        return [t for t in tools if t.spec.name not in abilities.HOST_ONLY], _named(folders)

    def _refusals(self, folders: list[prompt.Folder], exc: ValueError) -> list[prompt.Folder]:
        """Which folders the workbench refuses, each tried alone; when none is refused alone,
        the folders together are (the same folder twice), and all carry the reason."""
        assert self._project_tools is not None
        marked: list[prompt.Folder] = []
        for folder in folders:
            if folder.problem is None and len(_usable(folders)) > 1:
                try:
                    self._project_tools([folder.path], {})
                except ValueError as alone:
                    folder = dataclasses.replace(folder, problem=_reason(alone))
            marked.append(folder)
        if len(_usable(marked)) == len(_usable(folders)):
            marked = [f if f.problem else dataclasses.replace(f, problem=_reason(exc)) for f in folders]
        return marked

    @staticmethod
    def _report_refused(desk: Desk, folders: list[prompt.Folder]) -> None:
        refused = [f for f in folders if f.problem and f.problem != prompt.MISSING]
        if not refused:
            return
        if not _usable(folders):
            reasons = "; ".join(f"{f.given}: {f.problem}" for f in refused)
            desk.step("progress", f"Working without project tools: {reasons}")
            return
        for folder in refused:
            desk.step("progress", f"Working without the folder {folder.given}: {folder.problem}")

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
            library_text=resident_knowledge(self._config.paths.house),
            notes=notes.recent(prompt.NOTES_CHARS),
        )


def _level(agent: dict[str, Any], careful: bool) -> str:
    """The agent's effort from the plan: its heavy one for a careful job."""
    if careful:
        return str(agent.get("heavy_effort") or effort.CAREFUL)
    return str(agent.get("effort") or effort.RESIDENT)


def _folders(room: dict[str, Any] | None) -> list[prompt.Folder]:
    """The room's folders in order, a missing one marked as such."""
    given = room.get("folders") if room else None
    out: list[prompt.Folder] = []
    for folder in given if isinstance(given, list) else []:
        if isinstance(folder, str) and folder:
            path = Path(folder).expanduser()
            out.append(prompt.Folder(folder, path, None if path.is_dir() else prompt.MISSING))
    return out


def _usable(folders: Sequence[prompt.Folder]) -> list[prompt.Folder]:
    return [f for f in folders if f.problem is None]


def _named(folders: list[prompt.Folder]) -> tuple[prompt.Folder, ...]:
    """The usable folders with the short names the workbench gives them, which paths start with."""
    names = iter(folder_names([f.path for f in _usable(folders)]))
    return tuple(dataclasses.replace(f, name=next(names)) if f.problem is None else f for f in folders)


def _reason(exc: ValueError) -> str:
    return str(exc) or "the folder cannot be a project folder"
