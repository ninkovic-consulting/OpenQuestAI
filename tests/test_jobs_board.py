"""The job board: checks, queue and limits, cancelling, requests between residents,
restart recovery, persistence and events. The work is scripted."""

from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest
from jobs_fakes import make_board
from scheduler_fakes import until

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import AgentState, JobChanged, RoomState
from vision.jobs import MAX_ASKS, Board, Desk, Job, JobError, Outcome
from vision.jobs.board import RESTARTED
from vision.jobs.store import path_for


async def test_hand_off_checks(config: Config) -> None:
    board, work, spend, _ = await make_board(config)
    job = await board.hand_off("Tink", "Explain the project.")
    assert job.agent == "maker" and job.room == "workshop" and job.asked_by == "host"
    assert job.title == "Explain the project."
    by_id = await board.hand_off("checker", "Run the tests.", room="spare room", title="Tests")
    assert by_id.room == "spare-room" and by_id.title == "Tests"
    with pytest.raises(JobError, match="host and hands out work"):
        await board.hand_off("Vision", "Do it yourself.")
    with pytest.raises(JobError, match="no agent called 'Bob'.*Tink \\(maker\\)"):
        await board.hand_off("Bob", "x")
    visiting = await board.hand_off("Tock", "Test the maker's project.", room="Workshop")
    assert visiting.room == "workshop" and visiting.agent == "checker"
    with pytest.raises(JobError, match="Hall is the host's and nobody else works there"):
        await board.hand_off("Tock", "x", room="Hall")
    with pytest.raises(JobError, match="no room called"):
        await board.hand_off("Tock", "x", room="Ballroom")
    with pytest.raises(JobError, match="needs a brief"):
        await board.hand_off("Tock", "  ")
    with pytest.raises(JobError, match="at most 8000"):
        await board.hand_off("Tock", "x" * 8001)
    spend.out = True
    with pytest.raises(JobError, match="budget is used up.*no local model"):
        await board.hand_off("Tock", "Run the tests again.")
    await board.stop()


async def test_queue_order_limits_and_one_job_per_agent(config: Config) -> None:
    config.jobs.max_running = 2
    config.jobs.max_queued = 2
    board, work, _, _ = await make_board(config)
    a = await board.hand_off("Tink", "first for the maker")
    b = await board.hand_off("Tink", "second for the maker")
    c = await board.hand_off("Tock", "for the checker")
    d = await board.hand_off("Rook", "for the scout")
    assert [j.status for j in (a, b, c, d)] == ["working", "queued", "working", "queued"]
    with pytest.raises(JobError, match="2 jobs are already waiting"):
        await board.hand_off("Brass", "one too many")
    work.finish(c)
    await until(lambda: c.status == "done")
    assert d.status == "working" and b.status == "queued"  # the maker is still busy
    work.finish(a)
    await until(lambda: b.status == "working")
    assert c.result == "checker did for the checker"
    await board.stop()


async def test_raising_the_limit_starts_waiting_work(config: Config) -> None:
    config.jobs.max_running = 1
    board, _, _, _ = await make_board(config)
    await board.hand_off("Tink", "one")
    waiting = await board.hand_off("Tock", "two")
    assert waiting.status == "queued"
    config.jobs.max_running = 2
    board.pump()
    assert waiting.status == "working"
    await board.stop()


async def test_events_and_room_light(config: Config) -> None:
    bus = Bus()
    sub = bus.subscribe({JobChanged.TYPE, AgentState.TYPE, RoomState.TYPE})
    board, work, _, lights = await make_board(config, bus)
    job = await board.hand_off("Tink", "Explain the project.", title="Explain")
    work.finish(job)
    await until(lambda: job.status == "done")
    seen = []
    while not sub._queue.empty():  # noqa: SLF001 - drain what was published
        seen.append(await sub.get())
    kinds = [(e.TYPE, getattr(e, "status", getattr(e, "state", None))) for e in seen]
    assert kinds[0] == ("job.changed", "queued")
    assert ("job.changed", "working") in kinds and ("agent.state", "working") in kinds
    assert ("room.state", "active") in kinds and ("room.state", "dark") in kinds
    assert kinds[-1] == ("job.changed", "done") or ("job.changed", "done") in kinds
    done = next(e for e in seen if isinstance(e, JobChanged) and e.status == "done")
    assert done.last_step is not None and done.last_step.kind == "finished"
    assert done.data()["agent"] == "maker" and done.data()["room"] == "workshop"
    idle = [e for e in seen if isinstance(e, AgentState)][-1]
    assert idle.state == "idle" and idle.job is None
    assert lights == {"workshop": "dark"}
    assert board.agent_states()["maker"] == {"state": "idle", "job": None}
    await board.stop()


async def test_cancel_a_waiting_and_a_working_job(config: Config) -> None:
    config.jobs.max_running = 1
    board, work, _, _ = await make_board(config)
    running = await board.hand_off("Tink", "slow work")
    queued = await board.hand_off("Tock", "waits")
    await board.cancel(queued.id)
    assert queued.status == "cancelled" and queued.error == "Cancelled before it started."
    await board.cancel(running.id)
    assert running.status == "cancelled" and running.ended_at is not None
    with pytest.raises(JobError, match="already ended"):
        await board.cancel(running.id)
    assert board.agent_states()["maker"]["state"] == "idle"
    await board.stop()


async def test_a_request_between_residents_is_a_child_job(config: Config) -> None:
    board, work, _, _ = await make_board(config)
    answers: list[Job] = []

    async def maker(job: Job, desk: Desk) -> Outcome:
        answers.append(await desk.ask("Tock", "Run the tests and say which fail."))
        return Outcome("done", f"The checker said: {answers[0].result}")

    async def checker(job: Job, desk: Desk) -> Outcome:
        return Outcome("done", "test_b fails")

    work.scripts.update(maker=maker, checker=checker)
    parent = await board.hand_off("Tink", "Explain and test.")
    await until(lambda: parent.status == "done")
    child = answers[0]
    assert child.parent == parent.id and child.asked_by == "maker" and child.agent == "checker"
    assert child.room == "workshop" and child.status == "done"  # the parent's room, by default
    assert parent.result == "The checker said: test_b fails"
    assert any(s.kind == "request" and "Asked Tock" in s.text for s in parent.steps)
    await board.stop()


async def test_request_limits(config: Config) -> None:
    board, work, _, _ = await make_board(config)
    refusals: list[str] = []

    async def note(desk: Desk, agent: str) -> None:
        try:
            await desk.ask(agent, "help")
        except JobError as exc:
            refusals.append(str(exc))

    async def checker(job: Job, desk: Desk) -> Outcome:
        await note(desk, "Rook")  # a request cannot ask in turn
        return Outcome("done", "ok")

    async def scout(job: Job, desk: Desk) -> Outcome:
        return Outcome("done", "found")

    async def maker(job: Job, desk: Desk) -> Outcome:
        await note(desk, "Vision")
        await note(desk, "Tink")
        for _ in range(MAX_ASKS):
            await desk.ask("Rook", "look it up")
        await note(desk, "Rook")
        return Outcome("done", "done")

    work.scripts.update(maker=maker, checker=checker, scout=scout)
    job = await board.hand_off("Tink", "busy work")
    await until(lambda: job.status == "done")
    assert "host and hands out work" in refusals[0]
    assert refusals[1] == "That is you. Do it yourself."
    assert f"at most {MAX_ASKS} times" in refusals[2]
    child = await board.hand_off("Tock", "a direct job")
    await until(lambda: child.status == "done")
    work.scripts.pop("checker")
    # a request from a resident's request cannot ask anyone
    async def asking_checker(job: Job, desk: Desk) -> Outcome:
        await note(desk, "Rook")
        return Outcome("done", "ok")

    async def maker2(job: Job, desk: Desk) -> Outcome:
        await desk.ask("Tock", "please check")
        return Outcome("done", "ok")

    work.scripts.update(checker=asking_checker, maker=maker2)
    second = await board.hand_off("Tink", "again")
    await until(lambda: second.status == "done")
    assert "cannot ask anyone in turn" in refusals[-1]
    await board.stop()


async def test_a_busy_resident_is_refused_not_waited_for(config: Config) -> None:
    board, work, _, _ = await make_board(config)
    said: list[str] = []
    busy = await board.hand_off("Tock", "long checking")

    async def maker(job: Job, desk: Desk) -> Outcome:
        try:
            await desk.ask("Tock", "check this")
        except JobError as exc:
            said.append(str(exc))
        return Outcome("done", "did it myself")

    work.scripts["maker"] = maker
    job = await board.hand_off("Tink", "needs a check")
    await until(lambda: job.status == "done")
    assert "Tock is busy with another job ('long checking')" in said[0]
    work.finish(busy)
    await board.stop()


async def test_cancelling_a_job_cancels_its_request(config: Config) -> None:
    board, work, _, _ = await make_board(config)
    asked = asyncio.Event()

    async def maker(job: Job, desk: Desk) -> Outcome:
        asked.set()
        await desk.ask("Tock", "slow check")
        return Outcome("done", "never")

    work.scripts["maker"] = maker
    parent = await board.hand_off("Tink", "parent")
    await asked.wait()
    await until(lambda: any(j.parent == parent.id for j in board.all()))
    child = next(j for j in board.all() if j.parent == parent.id)
    await board.cancel(parent.id)
    assert parent.status == "cancelled" and child.status == "cancelled"
    assert board.agent_states()["checker"]["state"] == "idle"
    await board.stop()


async def test_timeout_and_failure_keep_what_was_done(config: Config) -> None:
    config.jobs.job_timeout_s = 0.05
    board, work, _, _ = await make_board(config)

    async def slow(job: Job, desk: Desk) -> Outcome:
        desk.partial = "read three files"
        await asyncio.sleep(5)
        return Outcome("done", "never")

    async def broken(job: Job, desk: Desk) -> Outcome:
        raise RuntimeError("boom")

    work.scripts.update(maker=slow, checker=broken)
    late = await board.hand_off("Tink", "slow")
    bad = await board.hand_off("Tock", "broken")
    await until(lambda: not late.open and not bad.open)
    assert late.status == "failed" and late.result == "read three files"
    assert "did not finish within 0.05 seconds" in late.error
    assert bad.status == "failed" and bad.error == "The work broke (RuntimeError)."
    await board.stop()


async def test_listeners_hear_only_top_level_jobs(config: Config) -> None:
    board, work, _, _ = await make_board(config)
    heard: list[str] = []
    board.listeners.append(lambda job: heard.append(job.id))

    async def maker(job: Job, desk: Desk) -> Outcome:
        await desk.ask("Tock", "x")
        return Outcome("done", "ok")

    async def checker(job: Job, desk: Desk) -> Outcome:
        return Outcome("done", "ok")

    work.scripts.update(maker=maker, checker=checker)
    job = await board.hand_off("Tink", "x")
    await until(lambda: job.status == "done")
    assert heard == [job.id]
    await board.stop()


async def test_saved_privately_and_recovered_after_a_restart(config: Config) -> None:
    board, work, _, _ = await make_board(config)
    done = await board.hand_off("Tock", "finished work")
    work.finish(done)
    await until(lambda: done.status == "done")
    cut = await board.hand_off("Tink", "cut short")
    await board.stop()
    path = path_for(config)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    saved = {j["id"]: j for j in json.loads(path.read_text())["jobs"]}
    assert saved[cut.id]["status"] == "working" and saved[done.id]["status"] == "done"

    again, _, _, _ = await make_board(config)
    restored = again.get(cut.id)
    assert restored is not None and restored.status == "failed" and restored.error == RESTARTED
    assert restored.steps[-1].text == RESTARTED
    assert again.get(done.id).status == "done"  # type: ignore[union-attr]
    await again.flushed()
    assert json.loads(path.read_text())["jobs"][-1]["status"] == "failed"
    await again.stop()


async def test_a_broken_file_is_moved_aside(config: Config) -> None:
    path = path_for(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    board = Board(config, Bus(), plan=dict, exhausted=lambda: False)
    await board.start(lambda job, desk: None)  # type: ignore[arg-type,return-value]
    assert board.all() == []
    assert path.with_name("jobs.json.broken").exists()


async def test_a_request_may_name_another_room(config: Config) -> None:
    board, work, _, _ = await make_board(config)
    asked: list[Job] = []

    async def maker(job: Job, desk: Desk) -> Outcome:
        asked.append(await desk.ask("Tock", "check the garage project", room="Garage"))
        try:
            await desk.ask("Rook", "look", room="Hall")
        except JobError as exc:
            return Outcome("done", str(exc))
        return Outcome("done", "no refusal")

    async def helper(job: Job, desk: Desk) -> Outcome:
        return Outcome("done", "ok")

    work.scripts.update(maker=maker, checker=helper, scout=helper)
    job = await board.hand_off("Tink", "x")
    await until(lambda: job.status == "done")
    assert asked[0].room == "garage" and "nobody else works there" in job.result
    await board.stop()
