"""The job board on a served daemon: routes, the host's tools, `/api/state`, the job turn,
the reporter, and the `[jobs]` settings."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from scheduler_fakes import until
from settings_fakes import client, use

from vision.app import Daemon
from vision.core.interfaces import TurnRecord
from vision.jobs import Job, Reporter
from vision.residents import NO_KEY
from vision.testing.fakes import FakeBrain

ROUTES = [("get", "/api/jobs"), ("get", "/api/jobs/x"), ("post", "/api/jobs"), ("post", "/api/jobs/x/cancel")]


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_routes_need_the_token(daemon: Daemon, method: str, path: str) -> None:
    async with client(daemon, token=False) as http:
        assert (await http.request(method, path, json={})).status_code == 401


async def test_start_list_look_and_refuse(daemon: Daemon) -> None:
    async with client(daemon) as http:
        made = await http.post("/api/jobs", json={"agent": "Tock", "brief": "Run the tests.", "title": "Tests"})
        assert made.status_code == 200
        job = made.json()["job"]
        assert made.json()["started"] is True
        assert job["agent"] == "checker" and job["room"] == "spare-room" and job["asked_by"] == "owner"
        assert set(job) == {
            "id", "title", "agent", "room", "status", "asked_by", "parent", "created_at", "started_at",
            "ended_at", "needed_approval", "last_step",
        }
        await until(lambda: daemon.board.get(job["id"]).status == "failed", timeout=5)  # type: ignore[union-attr]
        listing = (await http.get("/api/jobs?limit=5")).json()
        assert [j["id"] for j in listing["jobs"]] == [job["id"]]
        assert listing["agents"]["checker"] == {"state": "idle", "job": None}
        assert listing["limits"]["max_running"] == 2 and listing["limits"]["max_asks"] == 3
        one = (await http.get(f"/api/jobs/{job['id']}")).json()["job"]
        assert one["error"] == NO_KEY and one["brief"] == "Run the tests." and one["via"] == "window"
        assert [s["kind"] for s in one["steps"]] == ["started", "finished"]
        host = await http.post("/api/jobs", json={"agent": "host", "brief": "x"})
        odd = await http.post("/api/jobs", json={"agent": "Tock", "brief": "x", "colour": "red"})
        room = await http.post("/api/jobs", json={"agent": "Tock", "brief": "x", "room": "Hall"})
        missing = await http.get("/api/jobs/nope")
        ended = await http.post(f"/api/jobs/{job['id']}/cancel")
    assert host.status_code == 400 and "takes none" in host.json()["detail"]
    assert odd.status_code == 400 and room.status_code == 400 and "the host's and nobody else works there" in room.json()["detail"]
    assert missing.status_code == 404 and ended.status_code == 400 and "already ended" in ended.json()["detail"]


async def test_budget_refusal(daemon: Daemon) -> None:
    daemon.components.budget.set_cap(0.0)
    async with client(daemon) as http:
        refused = await http.post("/api/jobs", json={"agent": "Tink", "brief": "Build it."})
    assert refused.status_code == 400 and "no local model" in refused.json()["detail"]


async def test_state_shows_open_jobs_and_agents(daemon: Daemon) -> None:
    gate = asyncio.Event()

    async def wait(job: Job, desk: Any) -> Any:
        await gate.wait()
        raise asyncio.CancelledError

    daemon.board._work = wait  # noqa: SLF001 - hold the job open
    job = await daemon.board.hand_off("Tink", "Explain the project.")
    async with client(daemon) as http:
        state = (await http.get("/api/state")).json()
        cancelled = (await http.post(f"/api/jobs/{job.id}/cancel")).json()["job"]
    assert [j["id"] for j in state["jobs"]] == [job.id] and state["jobs"][0]["status"] == "working"
    assert state["agents"]["maker"] == {"state": "working", "job": job.id}
    assert "host" not in state["agents"]
    assert cancelled["status"] == "cancelled"


async def test_the_host_hands_off_and_hears_the_result_in_a_turn_of_its_own(daemon: Daemon) -> None:
    said = await daemon.components.tools.call(
        "hand_off", {"agent": "Rook", "brief": "Find the release date of Python 3.13.", "title": "Python date"}
    )
    assert said.ok and "Handed to Rook in the Attic as job" in said.content and "It has started." in said.content
    brain = daemon.components.brain
    assert isinstance(brain, FakeBrain)
    await until(lambda: any("[A job report" in text for text, _ in brain.sent), timeout=10)
    report = next(text for text, _ in brain.sent if "[A job report" in text)
    assert 'Rook\'s job' in report and '"Python date", failed: ' + NO_KEY in report
    await until(lambda: daemon.session is not None and not daemon.session.busy, timeout=5)
    history = await daemon.components.memory.history(5)
    assert history[-1].source == "job"
    listed = await daemon.components.tools.call("list_jobs", {})
    assert "Python date" in listed.content and "failed" in listed.content
    job_id = listed.content.split('\n')[1].split()[1]
    details = await daemon.components.tools.call("job_details", {"job": job_id})
    assert "Brief: Find the release date" in details.content and f"Problem: {NO_KEY}" in details.content
    refused = await daemon.components.tools.call("hand_off", {"agent": "Vision", "brief": "x"})
    assert not refused.ok and "takes none" in refused.content


async def test_the_reporter_waits_for_quiet_and_tells_the_phone() -> None:
    busy = [True]
    turns: list[tuple[str, bool]] = []
    phoned: list[str] = []

    async def run_turn(text: str, speak: bool) -> TurnRecord:
        turns.append((text, speak))
        return TurnRecord("t", 0, 0, "job", text, "Tock says the tests pass.", "ok", "fake", "fake")

    async def to_phone(text: str) -> None:
        phoned.append(text)

    reporter = Reporter(busy=lambda: busy[0], run_turn=run_turn, speak=lambda: False, to_phone=to_phone, name=str.title, poll_s=0.01)
    task = asyncio.create_task(reporter.run())
    job = Job("j1", "Tests", "Run them.", "checker", None, "done", "host", None, False, 0.0, via="phone", result="All pass.")
    reporter(job)
    await asyncio.sleep(0.05)
    assert turns == []
    busy[0] = False
    await until(lambda: bool(phoned))
    assert 'Checker finished job j1, "Tests".' in turns[0][0] and "All pass." in turns[0][0]
    assert turns[0][1] is False and phoned == ["Tock says the tests pass."]
    reporter(Job("j2", "Other", "x", "maker", None, "done", "host", None, False, 0.0, via="text", result="ok"))
    await until(lambda: len(turns) == 2)
    assert phoned == ["Tock says the tests pass."]
    task.cancel()


async def test_jobs_settings_are_checked_and_applied(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        bad = await http.patch(
            "/api/settings",
            json={"jobs": {"max_running": 0, "max_steps": 2.5, "timeout_s": 5, "max_job_usd": 0, "speak_results": "yes", "colour": 1}},
        )
        good = await http.patch(
            "/api/settings",
            json={"jobs": {"max_running": 3, "max_steps": 40, "timeout_s": 1800, "max_job_usd": 2.5, "speak_results": False}},
        )
    assert bad.status_code == 400
    fields = {e["field"] for e in bad.json()["detail"]["errors"]}
    assert fields == {"jobs.max_running", "jobs.max_steps", "jobs.timeout_s", "jobs.max_job_usd", "jobs.speak_results", "jobs.colour"}
    answer = good.json()
    assert answer["restart"] == [] and set(answer["applied"]) == {
        "jobs.max_running", "jobs.max_steps", "jobs.timeout_s", "jobs.max_job_usd", "jobs.speak_results",
    }
    jobs = daemon.config.jobs
    assert (jobs.max_running, jobs.max_steps, jobs.job_timeout_s, jobs.max_job_usd, jobs.speak_results) == (3, 40, 1800.0, 2.5, False)
    assert "max_running = 3" in daemon.config.paths.config_file.read_text()
