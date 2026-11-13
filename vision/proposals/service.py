"""`Proposals`: agents propose, the owner decides, approved tools run confined.

Everything the package does goes through here, so every change is saved,
published on the bus and, for the owner's decisions, written to the audit log.
The owner's decisions (`approve`, `decline`, `restore` and the made-tool
actions) are called only by the owner's routes. Nothing here subscribes to
`gate.decision` or reads a yes or no from text: a phone button, a spoken or a
typed yes settles gate requests, and a proposal is never one.

Its dependencies are injected so the tests run on fakes: the bus, the
assistant's home, the house plan, the audit log, the settings patch, the host's
current model and effort, the phone, the confinement and a clock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping
from pathlib import Path
from typing import Any, Protocol

from vision.core import effort
from vision.core.bus import Bus
from vision.core.events import (
    GateOutcome,
    MadeToolChange,
    MadeToolChanged,
    Notice,
    ProposalChanged,
)
from vision.core.interfaces import AuditRecord
from vision.gate.tools import Tool, ToolFailure
from vision.proposals import changes, made, sandbox, store, tools
from vision.proposals.made import MadeTool, Version
from vision.proposals.model import (
    HOST,
    NOTE_MAX,
    PER_AGENT,
    REASON_MAX,
    SCRIPT_MAX,
    TIERS,
    TOTAL,
    WHO,
    ChangePart,
    Context,
    Decision,
    Kind,
    MadeTier,
    NotFound,
    Proposal,
    ProposalError,
    ToolPart,
    Who,
)

log = logging.getLogger(__name__)

Settings = Callable[[dict[str, Any]], Awaitable[Any]]
"""The settings patch (`SettingsService.patch`): validates and applies, raises on a refusal."""
TellPhone = Callable[[str, str], Awaitable[None]]
"""Send a message to the paired phone: (key, text)."""
Confine = Callable[..., Awaitable[sandbox.RunResult]]
"""`sandbox.run_confined` or a stand-in with the same arguments."""


class Auditor(Protocol):
    async def audit(self, entry: AuditRecord) -> None: ...


class Proposals:
    def __init__(
        self,
        bus: Bus,
        home: Path,
        *,
        plan: Callable[[], dict[str, Any]],
        memory: Auditor,
        settings: Settings,
        host_now: Callable[[], tuple[str, str]],
        vault: Path | None = None,
        tell_phone: TellPhone | None = None,
        confine: Confine = sandbox.run_confined,
        confinement_problem: Callable[[], str | None] = sandbox.problem,
        reserved: Collection[str] = frozenset(),
        models: Callable[[], Collection[str]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """`home` is `$VISION_HOME`; `vault` the house folder (default `<home>/house`), which persona
        paths in the plan are relative to; `host_now` gives the host's (talk model, talk effort);
        `reserved` the built-in tool names a made tool may not take; `models` the Claude models the
        assistant knows (its price table): a proposed model must be one of them, so a misspelt
        name that settings would take as a custom model never reaches a job."""
        self._bus = bus
        self._home = home
        self._vault = vault if vault is not None else home / "house"
        self._plan = plan
        self._memory = memory
        self._settings = settings
        self._host_now = host_now
        self._tell_phone = tell_phone
        self._confine = confine
        self._problem = confinement_problem
        self._reserved = reserved
        self._models = models
        self._clock = clock
        self.path = home / store.FILE_NAME
        self._shelf = made.Shelf(home / made.FOLDER)
        self._items: dict[str, Proposal] = {p.id: p for p in store.load(self.path)}
        self._tools: dict[str, MadeTool] = self._shelf.load_all()
        self._verified: dict[str, tuple[int, made.StatKey]] = {}
        self._lock = asyncio.Lock()

    async def reload(self) -> None:
        """Read the proposals and the made tools again, after a reset or a restore replaced them."""
        async with self._lock:
            items = await asyncio.to_thread(store.load, self.path)
            tools = await asyncio.to_thread(self._shelf.load_all)
            self._items = {p.id: p for p in items}
            self._tools = tools
            self._verified = {}

    # ------------------------------------------------------------ reading

    def get(self, proposal_id: str) -> Proposal:
        found = self._items.get(proposal_id)
        if found is None:
            raise NotFound(f"There is no proposal {proposal_id!r}.")
        return found

    def listing(self, limit: int = 50) -> list[Proposal]:
        """Waiting ones oldest first, then decided ones newest first."""
        waiting = sorted((p for p in self._items.values() if p.waiting), key=lambda p: p.created_at)
        decided = sorted(
            (p for p in self._items.values() if not p.waiting),
            key=lambda p: p.decided_at or p.created_at,
            reverse=True,
        )
        return (waiting + decided)[:limit]

    def mine(self, agent: str) -> list[Proposal]:
        """The agent's own proposals, newest first."""
        return sorted((p for p in self._items.values() if p.agent == agent), key=lambda p: -p.created_at)

    def waiting_count(self) -> int:
        return sum(1 for p in self._items.values() if p.waiting)

    @staticmethod
    def limits() -> dict[str, int]:
        return {"per_agent": PER_AGENT, "total": TOTAL, "script_max": SCRIPT_MAX}

    def confinement(self) -> dict[str, Any]:
        """Whether made tools can run here, and in plain sentences what confinement does and does
        not enforce. Blocking the first time (a test run); routes call it in a thread."""
        problem = self._problem()
        return {
            "available": problem is None,
            "reason": problem,
            "enforced": list(sandbox.ENFORCED),
            "not_enforced": list(sandbox.NOT_ENFORCED),
        }

    # ------------------------------------------------------------ proposing

    async def propose_tool(self, ctx: Context, fields: Mapping[str, Any]) -> Proposal:
        """A new tool, or a new version of one the proposer wrote (the host may propose for any).
        A new version turns the tool off (`pending`) until the owner decides."""
        draft = made.draft(fields, ctx.folders, self._reserved)
        async with self._lock:
            self._room_for(ctx.agent)
            name = draft.name
            if any(p.waiting and p.tool is not None and p.tool.name == name for p in self._items.values()):
                raise ProposalError(f"A proposal for a tool called {name} is already waiting for the owner.")
            existing = self._tools.get(name)
            if existing is not None and ctx.agent not in (existing.author, HOST):
                raise ProposalError(
                    f"{name} is {existing.author_name}'s tool; only {existing.author_name} or the host can "
                    "propose a new version of it. Choose another name."
                )
            version = 1 if existing is None else max(v.version for v in existing.versions) + 1
            part = ToolPart(
                name=name,
                description=draft.description,
                input_schema=draft.input_schema,
                language=draft.language,
                script=draft.script,
                sha256=made.sha256(draft.script.encode("utf-8")),
                reach=draft.reach,
                version=version,
                replaces=None if existing is None else existing.version,
            )
            title = f"New tool {name}" if existing is None else f"New version {version} of {name}"
            proposal = self._new(ctx, "tool", title, draft.reason, tool=part)
            if existing is not None:
                existing.held = (existing.status, existing.disabled_reason)
                existing.status, existing.disabled_reason = "pending", made.PENDING_REASON
                await asyncio.to_thread(self._shelf.save, existing)
                self._bus.publish(MadeToolChanged(name=name, change="disabled", enabled=False))
            await self._arrived(proposal)
        await self._announce(proposal)
        return proposal

    async def propose_change(
        self, ctx: Context, field: Any, value: Any, reason: Any, agent: str | None = None
    ) -> Proposal:
        """A new persona, model or thinking level, for the proposer itself or (by the host) a
        resident. Anything else is refused here, whatever the model sent."""
        name = changes.check_field(field)
        target = self._target(ctx, agent)
        after = changes.check_value(name, value)
        if name == "model" and self._models is not None and after not in (known := self._models()):
            raise ProposalError(f"{after} is not a model this assistant knows. It knows {', '.join(sorted(known))}.")
        why = made.text(reason, "reason", REASON_MAX)
        words, target_name = changes.WORDS[name], str(target["name"])
        async with self._lock:
            self._room_for(ctx.agent)
            if any(
                p.waiting and p.change is not None and p.change.agent == target["id"] and p.change.field == name
                for p in self._items.values()
            ):
                raise ProposalError(f"A proposal to change {target_name}'s {words} is already waiting for the owner.")
            before = await self._now(target, name)
            if before == after or (name != "persona" and before.strip() == after):
                raise ProposalError(f"That is already {target_name}'s {words}.")
            if name == "effort":
                problem = effort.problem(self._model_of(str(target["id"])), after)
                if problem is not None:
                    raise ProposalError(problem)
            part = ChangePart(str(target["id"]), target_name, name, before, after)
            proposal = self._new(ctx, "change", f"{target_name}'s {words}", why, change=part)
            await self._arrived(proposal)
        await self._announce(proposal)
        return proposal

    def _room_for(self, agent: str) -> None:
        waiting = [p for p in self._items.values() if p.waiting]
        if sum(1 for p in waiting if p.agent == agent) >= PER_AGENT:
            raise ProposalError(
                f"You already have {PER_AGENT} proposals waiting for the owner. Wait until they decide "
                "before proposing more."
            )
        if len(waiting) >= TOTAL:
            raise ProposalError(
                f"The owner already has {TOTAL} proposals waiting. Wait until they decide before proposing more."
            )

    def _new(
        self,
        ctx: Context,
        kind: Kind,
        title: str,
        reason: str,
        *,
        tool: ToolPart | None = None,
        change: ChangePart | None = None,
    ) -> Proposal:
        proposal_id = uuid.uuid4().hex[:8]
        while proposal_id in self._items:
            proposal_id = uuid.uuid4().hex[:8]
        return Proposal(
            id=proposal_id,
            kind=kind,
            status="waiting",
            agent=ctx.agent,
            agent_name=ctx.agent_name,
            job=ctx.job,
            room=ctx.room,
            title=title,
            reason=reason,
            created_at=self._clock(),
            tool=tool,
            change=change,
        )

    async def _arrived(self, proposal: Proposal) -> None:
        self._items[proposal.id] = proposal
        await self._save()
        self._published(proposal)

    async def _announce(self, proposal: Proposal) -> None:
        """A notice in the window and a message to the phone, which can only point at the Mac."""
        first = self._headline(proposal)
        self._bus.publish(
            Notice(level="info", text=f"{first} Look at Proposals in the window to approve or decline it.")
        )
        if self._tell_phone is None:
            return
        text = f"{first} Look at Proposals on the Mac to decide; it cannot be approved from the phone."
        try:
            await self._tell_phone(f"proposal:{proposal.id}", text)
        except Exception:
            log.exception("could not tell the phone about proposal %s", proposal.id)

    @staticmethod
    def _headline(p: Proposal) -> str:
        if p.tool is not None:
            if p.tool.replaces is None:
                return f"{p.agent_name} proposes a new tool, {p.tool.name}."
            return f"{p.agent_name} proposes version {p.tool.version} of the tool {p.tool.name}."
        assert p.change is not None
        words = changes.WORDS[p.change.field]
        whose = "its" if p.change.agent == p.agent else f"{p.change.agent_name}'s"
        return f"{p.agent_name} proposes a change to {whose} {words}."

    # ------------------------------------------------------------ the owner decides

    async def approve(self, proposal_id: str, who: Any = "author", tier: Any = "ask") -> Proposal:
        """Approve a waiting proposal. A tool is written and turned on with `who` and `tier`; a
        change is applied through settings (or the persona file), and if that is refused the
        proposal stays waiting and the plain reason is raised."""
        async with self._lock:
            p = self._waiting(proposal_id)
            if p.tool is not None:
                if who not in WHO:
                    raise ProposalError("Who may use it is either author or everyone.")
                if tier not in TIERS:
                    raise ProposalError("A made tool either asks each time (ask) or runs freely (free).")
                await self._install(p, p.tool, who, tier)
                p.decision = Decision(who, tier)
            else:
                assert p.change is not None
                await self._apply(p.change, p.change.after)
            p.status, p.decided_at = "approved", self._clock()
            await self._save()
            self._published(p)
        await self._audit(p, "approve", "allow", "approved")
        return p

    async def decline(self, proposal_id: str, note: Any = "") -> Proposal:
        """Decline a waiting proposal. A declined new version puts its tool back as it was
        before the proposal: on again if it was on."""
        if not isinstance(note, str):
            raise ProposalError("The note must be text.")
        async with self._lock:
            p = self._waiting(proposal_id)
            tool = self._tools.get(p.tool.name) if p.tool is not None and p.tool.replaces is not None else None
            if tool is not None and tool.status == "pending" and tool.held is not None:
                tool.status, tool.disabled_reason = tool.held
                tool.held = None
                await asyncio.to_thread(self._shelf.save, tool)
                back: MadeToolChange = "enabled" if tool.enabled else "disabled"
                self._bus.publish(MadeToolChanged(name=tool.name, change=back, enabled=tool.enabled))
            p.status, p.decided_at, p.note = "declined", self._clock(), note.strip()[:NOTE_MAX]
            await self._save()
            self._published(p)
        await self._audit(p, "decline", "deny", "declined")
        return p

    async def restore(self, proposal_id: str) -> Proposal:
        """Put back the value an approved change replaced."""
        async with self._lock:
            p = self.get(proposal_id)
            if p.change is None or p.status != "approved":
                raise ProposalError("Only an approved change can be put back.")
            if p.restored_at is not None:
                raise ProposalError("This change was already put back.")
            await self._apply(p.change, p.change.before)
            p.restored_at = self._clock()
            await self._save()
            self._published(p)
        await self._audit(p, "restore", "allow", "put back as it was")
        return p

    def _waiting(self, proposal_id: str) -> Proposal:
        p = self.get(proposal_id)
        if not p.waiting:
            raise ProposalError(f"This proposal was already {p.status}.")
        return p

    async def _install(self, p: Proposal, part: ToolPart, who: Who, tier: MadeTier) -> None:
        if made.sha256(part.script.encode("utf-8")) != part.sha256:
            raise ProposalError("The proposal's script no longer matches its hash, so it cannot be approved. Decline it.")
        existing = self._tools.get(part.name)
        if part.replaces is None and existing is not None:
            raise ProposalError(f"There is already a tool called {part.name}. Decline this one.")
        if part.replaces is not None and existing is None:
            raise ProposalError(
                f"The tool {part.name} was deleted after this was proposed, so its new version cannot be "
                "approved. Decline it."
            )
        now = self._clock()
        version = Version(
            version=part.version,
            sha256=part.sha256,
            approved_at=now,
            proposal=p.id,
            language=part.language,
            description=part.description,
            input_schema=part.input_schema,
            reach=part.reach,
            reason=p.reason,
        )
        await asyncio.to_thread(self._shelf.write_version, part.name, part.version, part.language, part.script)
        if existing is None:
            tool = MadeTool(
                name=part.name,
                author=p.agent,
                author_name=p.agent_name,
                created_at=now,
                who=who,
                tier=tier,
                status="enabled",
                version=part.version,
                versions=[version],
            )
        else:
            tool = existing
            tool.versions.append(version)
            tool.version, tool.who, tool.tier = part.version, who, tier
            tool.status, tool.disabled_reason, tool.held = "enabled", "", None
        await asyncio.to_thread(self._shelf.save, tool)
        self._tools[tool.name] = tool
        self._verified.pop(tool.name, None)
        self._bus.publish(MadeToolChanged(name=tool.name, change="approved", enabled=True))

    # ------------------------------------------------------------ self-changes

    def _plan_agent(self, agent: str) -> dict[str, Any] | None:
        wanted = agent.strip().casefold()
        return next(
            (a for a in self._plan()["agents"] if a["id"] == agent or str(a["name"]).casefold() == wanted),
            None,
        )

    def _target(self, ctx: Context, agent: str | None) -> dict[str, Any]:
        wanted = agent if agent else ctx.agent
        found = self._plan_agent(wanted)
        if found is None:
            raise ProposalError(f"There is no agent called {wanted} in the house.")
        if ctx.agent != HOST and found["id"] != ctx.agent:
            raise ProposalError("You can propose a change only to yourself.")
        return found

    def _model_of(self, agent: str) -> str:
        if agent == HOST:
            return self._host_now()[0]
        found = self._plan_agent(agent)
        return str(found.get("model") or "") if found else ""

    async def _now(self, target: dict[str, Any], name: str) -> str:
        """The value now: the persona file's text, or the model or effort in use."""
        if name == "persona":
            path = changes.persona_path(self._vault, str(target.get("persona") or ""))
            return await asyncio.to_thread(changes.read_persona, path)
        if target["id"] == HOST:
            model, level = self._host_now()
            return model if name == "model" else level
        if name == "model":
            return str(target.get("model") or "")
        return str(target.get("effort") or effort.RESIDENT)

    async def _apply(self, change: ChangePart, value: str) -> None:
        if change.field == "persona":
            target = self._plan_agent(change.agent)
            if target is None:
                raise ProposalError(f"{change.agent_name} is no longer in the house.")
            path = changes.persona_path(self._vault, str(target.get("persona") or ""))
            try:
                await asyncio.to_thread(changes.write_persona, path, value)
            except OSError as exc:
                raise ProposalError(f"The persona file could not be written ({exc.strerror or exc}).") from None
            return
        if change.field == "effort":
            problem = effort.problem(self._model_of(change.agent), value)
            if problem is not None:
                raise ProposalError(problem)
        try:
            await self._settings(changes.settings_body(change.agent, change.field, value))
        except ValueError as exc:
            raise ProposalError(str(exc) or "Settings refused the change.") from None
        except Exception:
            log.exception("settings failed for a %s change", change.field)
            raise ProposalError("The change could not be applied: Settings failed.") from None

    # ------------------------------------------------------------ made tools for the agents

    def agent_tools(self, ctx: Context) -> list[Tool]:
        """propose_tool, propose_change and my_proposals for the agent in `ctx`."""
        return tools.agent_tools(self, ctx)

    def tools_for(self, ctx: Context) -> list[Tool]:
        """The approved, enabled tools this agent may use, as gate tools reaching at most its
        room's folders. Cheap enough for every listing: a script is hashed again only when its
        file's stat changed, and a script changed on disk turns its tool off here."""
        out: list[Tool] = []
        for name in sorted(self._tools):
            tool = self._tools[name]
            if not tool.enabled or (tool.who == "author" and tool.author != ctx.agent) or not self._intact(tool):
                continue
            reach = made.reach_for(tool.current.reach, ctx.folders)

            async def run(args: dict[str, Any], name: str = name) -> str:
                return await self._run(name, ctx, args)

            out.append(tools.made_tool(tool, reach, run))
        return out

    def _intact(self, tool: MadeTool) -> bool:
        now = tool.current
        key = self._shelf.stat_key(tool.name, now.version, now.language)
        if key is not None and self._verified.get(tool.name) == (now.version, key):
            return True
        data = self._shelf.read_version(tool.name, now.version, now.language)
        if data is None or made.sha256(data) != now.sha256:
            self._changed(tool)
            return False
        if key is not None:
            self._verified[tool.name] = (now.version, key)
        return True

    def _changed(self, tool: MadeTool) -> None:
        """The script on disk is not what the owner approved: turn the tool off and say so, once."""
        if tool.status == "changed":
            return
        tool.status, tool.disabled_reason, tool.held = "changed", made.CHANGED_REASON, None
        self._verified.pop(tool.name, None)
        try:
            self._shelf.save(tool)
        except OSError:
            log.exception("could not save the made tool %s", tool.name)
        self._bus.publish(MadeToolChanged(name=tool.name, change="disabled", enabled=False))
        self._bus.publish(
            Notice(
                level="warn",
                text=f"The script of the made tool {tool.name} changed on disk after you approved it, so it "
                "was turned off. Look at it under Proposals, Made tools.",
            )
        )

    async def _run(self, name: str, ctx: Context, args: dict[str, Any]) -> str:
        problem = await asyncio.to_thread(self._problem)
        if problem is not None:
            raise ToolFailure(f"{problem} The tool {name} did not run.")
        tool = self._tools.get(name)
        if tool is None or not tool.enabled or (tool.who == "author" and tool.author != ctx.agent):
            raise ToolFailure(f"The tool {name} is not available now, so it did not run.")
        now = tool.current
        data = await asyncio.to_thread(self._shelf.read_version, name, now.version, now.language)
        if data is None or made.sha256(data) != now.sha256:
            self._changed(tool)
            raise ToolFailure(
                f"The script of {name} changed on disk since the owner approved it, so it was turned off "
                "and did not run."
            )
        payload = made.checked_input(now.input_schema, args)
        reach = made.reach_for(now.reach, ctx.folders)
        scratch = await asyncio.to_thread(self._shelf.new_scratch, uuid.uuid4().hex[:12])
        try:
            result = await self._confine(
                now.language,
                data.decode("utf-8"),
                payload,
                reach=sandbox.Reach(read=tuple(path for _, path in reach), network=now.reach.network),
                scratch=scratch,
                deny=[self._home],
                env_extra={"FOLDERS": json.dumps({n: str(p) for n, p in reach}, ensure_ascii=False)},
                timeout=made.RUN_TIMEOUT_S,
                limit=made.OUTPUT_LIMIT,
            )
        except sandbox.Unavailable as exc:
            raise ToolFailure(f"{exc} The tool {name} did not run.") from None
        except ValueError as exc:
            raise ToolFailure(f"The tool {name} could not be started: {exc}.") from None
        finally:
            await asyncio.to_thread(shutil.rmtree, scratch, True)
        await self._record(tool, ctx, now, payload, result)
        return _answer(result)

    async def _record(
        self, tool: MadeTool, ctx: Context, now: Version, payload: bytes, result: sandbox.RunResult
    ) -> None:
        ts = self._clock()
        record = {
            "ts": ts,
            "agent": ctx.agent,
            "agent_name": ctx.agent_name,
            "job": ctx.job,
            "version": now.version,
            "sha256": now.sha256,
            "input": payload.decode("utf-8")[: made.RUN_INPUT_CLIP],
            "exit_code": result.exit_code,
            "seconds": round(result.seconds, 3),
            "output": result.output[: made.RUN_OUTPUT_CLIP],
            "truncated": result.truncated,
            "swept": result.swept,
        }
        async with self._lock:
            if self._tools.get(tool.name) is not tool:
                return  # deleted while it ran
            tool.runs += 1
            tool.last_run = {"ts": ts, "agent": ctx.agent, "exit_code": result.exit_code, "ok": result.exit_code == 0}
            await asyncio.to_thread(self._shelf.add_run, tool.name, record)
            await asyncio.to_thread(self._shelf.save, tool)
        self._bus.publish(MadeToolChanged(name=tool.name, change="ran", enabled=tool.enabled))

    # ------------------------------------------------------------ made tools for the owner

    def _made(self, name: str) -> MadeTool:
        tool = self._tools.get(name)
        if tool is None:
            raise NotFound(f"There is no made tool {name!r}.")
        return tool

    def made_list(self) -> list[dict[str, Any]]:
        out = []
        for name in sorted(self._tools):
            tool = self._tools[name]
            if tool.enabled:
                self._intact(tool)
            out.append(tool.summary())
        return out

    async def made_get(self, name: str) -> dict[str, Any]:
        """The summary with every version's script, and the newest runs."""
        tool = self._made(name)
        if tool.enabled:
            self._intact(tool)

        def scripts() -> dict[int, str]:
            out = {}
            for v in tool.versions:
                data = self._shelf.read_version(name, v.version, v.language)
                out[v.version] = "" if data is None else data.decode("utf-8", errors="replace")
            return out

        texts = await asyncio.to_thread(scripts)
        detail = tool.summary()
        detail["script"] = texts.get(tool.version, "")
        detail["versions"] = [{**v.listed(), "script": texts.get(v.version, "")} for v in tool.versions]
        return {"tool": detail, "runs": await asyncio.to_thread(self._shelf.runs, name)}

    async def made_update(
        self, name: str, *, tier: Any = None, who: Any = None, enabled: Any = None
    ) -> dict[str, Any]:
        """Change who may use a tool, its tier, or turn it on or off. A script changed on disk
        cannot be turned on again: go back to an approved version instead."""
        if tier is not None and tier not in TIERS:
            raise ProposalError("A made tool either asks each time (ask) or runs freely (free).")
        if who is not None and who not in WHO:
            raise ProposalError("Who may use it is either author or everyone.")
        if enabled is not None and not isinstance(enabled, bool):
            raise ProposalError("enabled must be true or false.")
        async with self._lock:
            tool = self._made(name)
            toggled = enabled is not None and enabled != tool.enabled
            if toggled and tool.status == "pending":
                raise ProposalError(
                    f"A new version of {name} waits for your decision in Proposals; approve or decline it first."
                )
            if toggled and enabled:
                if tool.status == "changed" or not await self._matches(tool, tool.current):
                    self._changed(tool)
                    raise ProposalError(
                        f"The script of {name} changed on disk since you approved it, so it cannot be turned "
                        "on. Go back to an approved version instead."
                    )
                tool.status, tool.disabled_reason = "enabled", ""
            elif toggled:
                tool.status, tool.disabled_reason = "disabled", made.OFF_REASON
            if tier is not None:
                tool.tier = tier
            if who is not None:
                tool.who = who
            await asyncio.to_thread(self._shelf.save, tool)
        change: MadeToolChange = ("enabled" if tool.enabled else "disabled") if toggled else "updated"
        self._bus.publish(MadeToolChanged(name=name, change=change, enabled=tool.enabled))
        return tool.summary()

    async def made_use_version(self, name: str, n: int) -> dict[str, Any]:
        """Go back (or forward) to an approved version, whose own pinned hash must still match."""
        async with self._lock:
            tool = self._made(name)
            if tool.status == "pending":
                raise ProposalError(
                    f"A new version of {name} waits for your decision in Proposals; approve or decline it first."
                )
            version = tool.find(n)
            if version is None:
                raise NotFound(f"{name} has no version {n}.")
            if not await self._matches(tool, version):
                raise ProposalError(
                    f"Version {n} of {name} on disk no longer matches what you approved, so it cannot be used."
                )
            tool.version, tool.status, tool.disabled_reason = n, "enabled", ""
            self._verified.pop(name, None)
            await asyncio.to_thread(self._shelf.save, tool)
        self._bus.publish(MadeToolChanged(name=name, change="updated", enabled=True))
        return tool.summary()

    async def made_delete(self, name: str) -> None:
        async with self._lock:
            self._made(name)
            del self._tools[name]
            self._verified.pop(name, None)
            await asyncio.to_thread(self._shelf.remove, name)
        self._bus.publish(MadeToolChanged(name=name, change="deleted", enabled=False))

    async def _matches(self, tool: MadeTool, version: Version) -> bool:
        data = await asyncio.to_thread(self._shelf.read_version, tool.name, version.version, version.language)
        return data is not None and made.sha256(data) == version.sha256

    # ------------------------------------------------------------ saving, events, audit

    async def _save(self) -> None:
        kept = store.pruned(list(self._items.values()))
        self._items = {p.id: p for p in kept}
        await asyncio.to_thread(store.save, self.path, [p.detail() for p in kept])

    def _published(self, p: Proposal) -> None:
        self._bus.publish(
            ProposalChanged(id=p.id, kind=p.kind, status=p.status, agent=p.agent, waiting=self.waiting_count())
        )

    async def _audit(self, p: Proposal, action: str, decision: GateOutcome, result: str) -> None:
        args: dict[str, Any] = {"id": p.id, "kind": p.kind, "action": action, "agent": p.agent}
        if p.tool is not None:
            args |= {"name": p.tool.name, "version": p.tool.version, "sha256": p.tool.sha256}
            if p.decision is not None and action == "approve":
                args |= p.decision.to_dict()
        if p.change is not None:
            args |= {"field": p.change.field, "for": p.change.agent}
        entry = AuditRecord(
            ts=self._clock(),
            tool="proposal",
            args=args,
            tier="owner",
            decision=decision,
            result=result,
            agent=p.agent,
            job=p.job,
        )
        try:
            await self._memory.audit(entry)
        except Exception:
            log.exception("could not audit the %s of proposal %s", action, p.id)


def _answer(result: sandbox.RunResult) -> str:
    """What the model hears: the exit code and the output, or a plain line for a timeout."""
    output = result.output.rstrip() + ("\n[output truncated]" if result.truncated else "")
    if result.exit_code is None:
        raise ToolFailure(
            f"The tool did not finish within {made.RUN_TIMEOUT_S:g} seconds and was stopped.\n{output}".rstrip()
        )
    report = f"exit code {result.exit_code}\n{output}".rstrip()
    if result.exit_code != 0:
        raise ToolFailure(report)
    return report
