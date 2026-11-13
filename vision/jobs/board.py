"""The job board: the hub through which every piece of a resident's work passes.

Only the host (and the owner, from the window) hands out work, and residents
never give each other orders: a resident that needs help posts a request
here, which runs as a child job of its own. The board

- checks a hand-off (the agent exists and is not the host, the room exists
  and is not the Hall, the residents can work now, the queue is not full).
  Whether they can work is asked of `refusal`: in offline mode the local
  model must be on disk and able to call tools; with the month's budget used
  up the local model takes the work when it can, else the hand-off is
  refused. A resident may work in another agent's room, where the project the
  work is about lives; a request between residents runs in the asking job's
  room unless it names another;
- runs at most `[jobs] max_running` jobs at once and never two for one
  agent (on the local model they work side by side, but their generations
  take turns in the engine, the host's first); the rest wait in the order they came. A child job runs at once
  beside its parent (which is blocked waiting for it), so it does not take a
  place of its own, and is refused when the agent it asks for is busy:
  waiting there could deadlock two residents asking each other;
- stops a job at `[jobs] job_timeout_s`, and cancels one cleanly (its child
  first) when asked;
- keeps every job in `jobs.json`, and on start marks any job the daemon did
  not see to the end as failed;
- publishes `job.changed`, `agent.state` and the job room's `room.state`.

The work itself (`Work`) is injected: the residents' sessions in the
daemon, a script in the tests. A running job reaches the board through its
`Desk`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import AgentState, AgentWork, JobStatus, RoomLight, RoomState
from vision.house.project import rooms_named
from vision.jobs import store
from vision.jobs.model import BRIEF_MAX, RESULT_MAX, TITLE_MAX, Job, Step, StepKind, clip

log = logging.getLogger(__name__)

HOST = "host"
MAX_ASKS = 3
"""Requests to other residents one job may make."""
RESTARTED = "The daemon restarted before it finished."


class JobError(ValueError):
    """A hand-off, request or cancel that cannot be done; the message is for people."""


class NotFound(LookupError):
    def __init__(self, ref: str) -> None:
        super().__init__(f"There is no job {ref!r}.")


@dataclass(frozen=True, slots=True)
class Outcome:
    status: Literal["done", "failed"]
    result: str
    error: str = ""


Work = Callable[[Job, "Desk"], Awaitable[Outcome]]
Listener = Callable[[Job], None]


@dataclass(slots=True)
class Desk:
    """What a running job can do on the board. It is also the gate's `JobHooks`."""

    board: Board
    job: Job
    partial: str = ""
    """The resident's words so far: the result if the job is stopped before it ends."""
    asks: int = 0
    _waits: int = field(default=0, repr=False)

    def step(self, kind: StepKind, text: str) -> None:
        self.job.add_step(Step(self.board.clock(), kind, text))
        self.board.changed(self.job)

    def using(self, model: str, *, local: bool) -> None:
        """Record the model the job runs on, and whether it is the local one."""
        self.job.model, self.job.local = model, local
        self.board.changed(self.job)

    def charge(self, usd: float) -> bool:
        """Add a model call's cost; True when the job's own cost has passed the cap."""
        self.job.cost_usd += usd
        return self.job.cost_usd > self.board.config.jobs.max_job_usd

    def waiting(self, waiting: bool) -> None:
        self._waits += 1 if waiting else -1
        self.board.set_agent(self.job.agent, "waiting" if self._waits > 0 else "working", self.job.id)

    def unanswered(self) -> None:
        self.job.needed_approval = True
        self.board.changed(self.job)

    async def ask(self, agent: str, brief: str, room: str | None = None) -> Job:
        """Post a request for another resident, run it, and return it once it has ended. It
        runs in this job's room unless another is named."""
        return await self.board.ask(self, agent, brief, room)


class Board:
    def __init__(
        self,
        config: Config,
        bus: Bus,
        *,
        plan: Callable[[], dict[str, Any]],
        refusal: Callable[[], Awaitable[str | None]],
        light: Callable[[str, RoomLight], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.bus = bus
        self._plan = plan
        self._refusal = refusal
        self._light = light
        self.clock = clock
        self.path = store.path_for(config)
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._desks: dict[str, Desk] = {}
        self._agents: dict[str, tuple[AgentWork, str | None]] = {}
        self._lit: dict[str, RoomLight] = {}
        self._work: Work | None = None
        self._stopping = False
        self._dirty = False
        self._saving: asyncio.Task[None] | None = None
        self.listeners: list[Listener] = []
        """Called with every top-level job that ends (the host reports it)."""

    # ------------------------------------------------------------ lifetime

    async def start(self, work: Work) -> None:
        """Load the board, fail what a restart cut short, and start what waits."""
        await self._load()
        self._work = work
        self._stopping = False

    async def stop(self) -> None:
        """Stop the work in progress without recording an end: the next start marks it failed."""
        self._stopping = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.flushed()

    async def flushed(self) -> None:
        """Wait until the file holds every change made so far."""
        while self._saving is not None and not self._saving.done():
            await asyncio.gather(self._saving, return_exceptions=True)

    async def settle(self) -> None:
        """Cancel every open job and wait for the file (before a reset or a restore moves it)."""
        for job in self.open_jobs():
            if job.open:
                await self.cancel(job.id)
        await self.flushed()

    async def reload(self) -> None:
        """Read the file again after a reset or a restore. Call `settle` first."""
        await self.settle()
        await self._load()

    async def _load(self) -> None:
        """Read the file; a job still open in it was cut short and is marked failed."""
        loaded = await asyncio.to_thread(store.load, self.path)
        self._jobs = {j.id: j for j in loaded}
        now = self.clock()
        cut = [j for j in loaded if j.open]
        for job in cut:
            job.status, job.ended_at, job.error = "failed", now, RESTARTED
            job.add_step(Step(now, "finished", RESTARTED))
        if cut:
            self._save()

    # ------------------------------------------------------------ reading

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def find(self, ref: str) -> Job:
        """By id, or by title when exactly one job has it."""
        ref = ref.strip()
        if ref in self._jobs:
            return self._jobs[ref]
        wanted = ref.casefold()
        named = [j for j in self._jobs.values() if j.title.casefold() == wanted]
        if len(named) == 1:
            return named[0]
        raise NotFound(ref)

    def all(self, limit: int = 50) -> list[Job]:
        """Newest first."""
        return sorted(self._jobs.values(), key=lambda j: (j.created_at, j.id), reverse=True)[:limit]

    def open_jobs(self) -> list[Job]:
        """Jobs at work and waiting, oldest first."""
        return sorted((j for j in self._jobs.values() if j.open), key=lambda j: (j.created_at, j.id))

    def current(self, agent: str) -> Job | None:
        """The job the agent is working on now."""
        return next((j for j in self._jobs.values() if j.agent == agent and j.status == "working"), None)

    def agent_states(self) -> dict[str, dict[str, Any]]:
        """Every resident's `agent.state`, idle ones included."""
        out = {a["id"]: {"state": "idle", "job": None} for a in self._plan()["agents"] if a["id"] != HOST}
        for agent, (state, job) in self._agents.items():
            out[agent] = {"state": state, "job": job}
        return out

    def agent_name(self, agent_id: str) -> str:
        return next((a["name"] for a in self._plan()["agents"] if a["id"] == agent_id), agent_id)

    def room_name(self, room_id: str | None) -> str | None:
        if room_id is None:
            return None
        return next((r["name"] for r in self._plan()["rooms"] if r["id"] == room_id), room_id)

    # ------------------------------------------------------------ handing off

    async def hand_off(
        self,
        agent: str,
        brief: str,
        *,
        room: str | None = None,
        title: str | None = None,
        careful: bool = False,
        asked_by: str = HOST,
        via: str = "",
    ) -> Job:
        """Check and queue a job; it starts at once when a place and the agent are free."""
        plan = self._plan()
        agent_id = self._resident(plan, agent)
        room_id = self._room(plan, agent_id, room)
        text = _brief(brief)
        await self._affordable()
        waiting = sum(1 for j in self._jobs.values() if j.status == "queued")
        if waiting >= self.config.jobs.max_queued:
            raise JobError(
                f"{waiting} jobs are already waiting, the most allowed. Wait for some to finish "
                "or cancel one."
            )
        job = self._new(agent_id, room_id, text, title, careful, asked_by, None, via)
        self.pump()
        return job

    async def ask(self, desk: Desk, agent: str, brief: str, room: str | None = None) -> Job:
        """A resident's request for another resident, run as a child job in the parent's room
        (or the one named); waits for its end."""
        parent = desk.job
        if parent.parent is not None:
            raise JobError(
                "This is already a request from another resident, so it cannot ask anyone in "
                "turn. Do it yourself, or say in your result what is still needed."
            )
        if desk.asks >= MAX_ASKS:
            raise JobError(f"A job may ask other residents at most {MAX_ASKS} times; this one has.")
        plan = self._plan()
        agent_id = self._resident(plan, agent)
        if agent_id == parent.agent:
            raise JobError("That is you. Do it yourself.")
        busy = self.current(agent_id)
        if busy is not None:
            raise JobError(
                f"{self.agent_name(agent_id)} is busy with another job ({busy.title!r}) right now. "
                "Do it yourself, or say in your result that it is still needed."
            )
        text = _brief(brief)
        await self._affordable()
        room_id = self._room(plan, agent_id, room, default=parent.room)
        desk.asks += 1
        child = self._new(agent_id, room_id, text, None, False, parent.agent, parent.id, "")
        desk.step("request", f"Asked {self.agent_name(agent_id)}: {child.title} (job {child.id})")
        self._begin(child)
        task = self._tasks[child.id]
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            await self.cancel(child.id)
            raise
        return child

    async def cancel(self, ref: str) -> Job:
        """Stop a job (and the requests it made) and record it as cancelled."""
        job = self.find(ref)
        if not job.open:
            raise JobError(f"Job {job.id} ({job.title!r}) has already ended ({job.status}).")
        task = self._tasks.get(job.id)
        if task is None:
            self._end(job, "cancelled", "", "Cancelled before it started.")
            return job
        if not self._stopping:
            job.status = "cancelled"  # read by `_run` when the cancellation arrives
        task.cancel()  # a request it is waiting on is cancelled on the way out (`ask`)
        await asyncio.gather(task, return_exceptions=True)
        if job.ended_at is None and not self._stopping:  # cancelled before its work began
            self._end(job, "cancelled", "", "Cancelled.")
        for child in [j for j in self._jobs.values() if j.parent == job.id and j.open]:
            await self.cancel(child.id)
        return job

    # ------------------------------------------------------------ checks

    def _resident(self, plan: dict[str, Any], ref: str) -> str:
        if not isinstance(ref, str) or not ref.strip():
            raise JobError("Say which agent should do it.")
        wanted = ref.strip().casefold()
        agents = plan["agents"]
        found = next((a for a in agents if wanted in (a["id"].casefold(), a["name"].casefold())), None)
        residents = ", ".join(f"{a['name']} ({a['id']})" for a in agents if a["id"] != HOST)
        if found is None:
            raise JobError(f"There is no agent called {ref!r}. The residents are: {residents}.")
        if found["id"] == HOST:
            raise JobError(
                f"{found['name']} is the host and hands out work but takes none. The residents are: "
                f"{residents}."
            )
        return str(found["id"])

    def _room(
        self, plan: dict[str, Any], agent_id: str, ref: str | None, default: str | None = None
    ) -> str | None:
        """Any room but the Hall, found by id, name or project name: a resident may work where
        the project lives. Without one, the given default, else the agent's first room."""
        rooms = [r for r in plan["rooms"] if r["agent"] == agent_id]
        if ref is None or not str(ref).strip():
            if default is not None:
                return default
            return rooms[0]["id"] if rooms else None
        wanted = str(ref).strip().casefold()
        found = next(
            (r for r in plan["rooms"] if wanted in (r["id"].casefold(), r["name"].casefold())), None
        )
        if found is None:
            named = rooms_named(plan["rooms"], wanted)
            if len(named) > 1:
                both = " and ".join(f"the {r['name']} (id {r['id']})" for r in named)
                raise JobError(
                    f"More than one room holds the project {str(ref).strip()!r}: {both}. "
                    "Name the room by its name or id."
                )
            found = named[0] if named else None
        if found is None:
            names = ", ".join(r["name"] for r in plan["rooms"] if r["agent"] != HOST)
            raise JobError(f"There is no room called {ref!r}. The rooms are: {names}.")
        if found["agent"] == HOST:
            raise JobError(
                f"The {found['name']} is the host's and nobody else works there. Choose the room "
                "whose project the work is about, or leave the room out."
            )
        return str(found["id"])

    async def _affordable(self) -> None:
        reason = await self._refusal()
        if reason is not None:
            raise JobError(reason)

    # ------------------------------------------------------------ running

    def _new(
        self,
        agent: str,
        room: str | None,
        brief: str,
        title: str | None,
        careful: bool,
        asked_by: str,
        parent: str | None,
        via: str,
    ) -> Job:
        name = title.strip() if isinstance(title, str) and title.strip() else brief.splitlines()[0]
        job = Job(
            id=uuid.uuid4().hex[:8],
            title=clip(" ".join(name.split()), TITLE_MAX),
            brief=brief,
            agent=agent,
            room=room,
            status="queued",
            asked_by=asked_by,
            parent=parent,
            careful=bool(careful),
            created_at=self.clock(),
            via=via,
        )
        self._jobs[job.id] = job
        self.changed(job)
        return job

    def pump(self) -> None:
        """Start waiting jobs, oldest first, while places and their agents are free."""
        if self._work is None or self._stopping:
            return
        for job in self.open_jobs():
            running = sum(1 for j in self._jobs.values() if j.status == "working" and j.parent is None)
            if running >= self.config.jobs.max_running:
                return
            if job.status == "queued" and self.current(job.agent) is None:
                self._begin(job)

    def _begin(self, job: Job) -> None:
        assert self._work is not None
        job.status, job.started_at = "working", self.clock()
        room = self.room_name(job.room)
        where = f" in the {room}" if room else ""
        job.add_step(Step(job.started_at, "started", f"{self.agent_name(job.agent)} started{where}."))
        self.changed(job)
        self.set_agent(job.agent, "working", job.id)
        self._room_light(job.room, True)
        desk = self._desks[job.id] = Desk(self, job)
        self._tasks[job.id] = asyncio.create_task(self._run(job, desk), name=f"job-{job.id}")

    async def _run(self, job: Job, desk: Desk) -> None:
        assert self._work is not None
        timeout = self.config.jobs.job_timeout_s
        status: JobStatus
        try:
            outcome = await asyncio.wait_for(self._work(job, desk), timeout)
            status, result, error = outcome.status, outcome.result, outcome.error
        except TimeoutError:
            status, result = "failed", desk.partial
            error = f"It did not finish within {_duration(timeout)} and was stopped."
        except asyncio.CancelledError:
            if self._stopping:
                raise
            status, result, error = "cancelled", desk.partial, "Cancelled."
        except Exception as exc:
            log.exception("job %s failed", job.id)
            status, result, error = "failed", desk.partial, f"The work broke ({type(exc).__name__})."
        if job.status == "cancelled":
            status, error = "cancelled", "Cancelled."
        self._end(job, status, result, error)

    def _end(self, job: Job, status: JobStatus, result: str, error: str) -> None:
        was_working = job.started_at is not None
        job.status, job.ended_at = status, self.clock()
        job.result, job.error = clip(result, RESULT_MAX), error
        said = {"done": "Finished.", "failed": f"Failed: {error}", "cancelled": "Cancelled."}[status]
        job.add_step(Step(job.ended_at, "finished", said))
        self._tasks.pop(job.id, None)
        self._desks.pop(job.id, None)
        self.changed(job)
        if was_working:
            self.set_agent(job.agent, "idle", None)
            self._room_light(job.room, False)
        if job.parent is None:
            for listener in self.listeners:
                try:
                    listener(job)
                except Exception:
                    log.exception("a job listener failed")
        self.pump()

    # ------------------------------------------------------------ announcing

    def changed(self, job: Job) -> None:
        self.bus.publish(job.event())
        self._save()

    def set_agent(self, agent: str, state: AgentWork, job: str | None) -> None:
        if self._agents.get(agent) == (state, job):
            return
        self._agents[agent] = (state, job)
        self.bus.publish(AgentState(agent=agent, state=state, job=job))

    def _room_light(self, room: str | None, active: bool) -> None:
        if room is None:
            return
        if active:
            before: RoomLight = next((r["state"] for r in self._plan()["rooms"] if r["id"] == room), "dark")
            self._lit.setdefault(room, before)
            light: RoomLight = "active"
        elif any(j.room == room and j.status == "working" for j in self._jobs.values()):
            return
        else:
            light = self._lit.pop(room, "dark")
        if self._light is not None:
            try:
                self._light(room, light)
            except KeyError:
                return
        self.bus.publish(RoomState(room=room, state=light))

    def _save(self) -> None:
        self._dirty = True
        if self._saving is None or self._saving.done():
            self._saving = asyncio.get_running_loop().create_task(self._flush())

    async def _flush(self) -> None:
        while self._dirty:
            self._dirty = False
            kept = store.pruned(list(self._jobs.values()))
            if len(kept) != len(self._jobs):
                self._jobs = {j.id: j for j in kept}
            rows = [j.to_dict() for j in kept]
            try:
                await asyncio.to_thread(store.save, self.path, rows)
            except OSError as exc:
                log.warning("could not save the job board: %s", exc)


def _brief(brief: Any) -> str:
    if not isinstance(brief, str) or not brief.strip():
        raise JobError("A job needs a brief that says what to do.")
    text = brief.strip()
    if len(text) > BRIEF_MAX:
        raise JobError(f"A brief can be at most {BRIEF_MAX} characters; this one has {len(text)}.")
    return text


def _duration(seconds: float) -> str:
    if seconds >= 120:
        return f"{seconds / 60:g} minutes"
    return f"{seconds:g} seconds"
