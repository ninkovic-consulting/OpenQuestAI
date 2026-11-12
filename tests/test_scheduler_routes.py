"""The automation routes on a served daemon, limits, persistence, reset, and a run end to end."""

from __future__ import annotations

import json
import os
import stat
from typing import Any

from scheduler_fakes import until
from settings_fakes import client, use

from vision.app import Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import AutomationChanged, AutomationFinished, AutomationStarted, StateChanged, VisionReply
from vision.scheduler import Automations
from vision.scheduler.model import INSTRUCTION_MAX, MAX_AUTOMATIONS

DAILY = {"kind": "daily", "time": "09:00"}


def body(name: str = "Morning", **more: Any) -> dict[str, Any]:
    return {"name": name, "instruction": "Read me the weather.", "schedule": DAILY, **more}


async def test_routes_need_the_token(daemon: Daemon) -> None:
    async with client(daemon, token=False) as http:
        assert (await http.get("/api/automations")).status_code == 401
        assert (await http.post("/api/automations", json=body())).status_code == 401
        assert (await http.patch("/api/automations/x", json={})).status_code == 401
        assert (await http.delete("/api/automations/x")).status_code == 401
        assert (await http.post("/api/automations/x/run")).status_code == 401


async def test_create_list_change_and_delete(daemon: Daemon) -> None:
    changes = daemon.bus.subscribe({AutomationChanged.TYPE})
    async with client(daemon) as http:
        created = await http.post("/api/automations", json=body(speak=False))
        assert created.status_code == 200
        a = created.json()["automation"]
        assert a["name"] == "Morning" and a["speak"] is False and a["paused"] is False
        assert a["words"] == "every day at 09:00" and a["next_run"] > 0 and a["results"] == []
        listing = (await http.get("/api/automations")).json()
        assert [x["id"] for x in listing["automations"]] == [a["id"]]
        assert listing["limits"] == {"max_automations": MAX_AUTOMATIONS, "name_max": 60, "instruction_max": INSTRUCTION_MAX}
        assert isinstance(listing["timezone"], str)
        patched = (await http.patch(f"/api/automations/{a['id']}", json={"paused": True, "name": "Weather"})).json()
        assert patched["automation"]["paused"] is True and patched["automation"]["next_run"] is None
        assert (await http.delete(f"/api/automations/{a['id']}")).json() == {"deleted": a["id"]}
        assert (await http.get("/api/automations")).json()["automations"] == []
    kinds = [(await changes.get()) for _ in range(3)]
    assert [k.change for k in kinds if isinstance(k, AutomationChanged)] == ["created", "updated", "deleted"]


async def test_refusals_are_clear(daemon: Daemon) -> None:
    async with client(daemon) as http:
        assert (await http.patch("/api/automations/nope", json={"paused": True})).status_code == 404
        assert (await http.delete("/api/automations/nope")).status_code == 404
        assert (await http.post("/api/automations/nope/run")).status_code == 404
        bad = await http.post("/api/automations", json=body(schedule={"kind": "interval", "every": 0, "unit": "minutes"}))
        assert bad.status_code == 400 and "1 or more" in bad.json()["detail"]
        long = await http.post("/api/automations", json=body(instruction="x" * (INSTRUCTION_MAX + 1)))
        assert long.status_code == 400 and f"at most {INSTRUCTION_MAX} characters" in long.json()["detail"]
        missing = await http.post("/api/automations", json={"name": "x"})
        assert missing.json()["detail"] == "An automation needs instruction, schedule."
        await http.post("/api/automations", json=body())
        twin = await http.post("/api/automations", json=body(name="morning"))
        assert twin.status_code == 400 and "already an automation called 'Morning'" in twin.json()["detail"]
        assert (await http.post("/api/automations", content=b"[1]")).status_code == 400


async def test_at_most_fifty(daemon: Daemon) -> None:
    for n in range(MAX_AUTOMATIONS):
        await daemon.automations.create(body(f"Job {n}"))
    async with client(daemon) as http:
        refused = await http.post("/api/automations", json=body("One more"))
    assert refused.status_code == 400
    assert refused.json()["detail"] == "There are already 50 automations, the most allowed. Delete one first."


async def test_automations_survive_a_restart_in_a_private_file(config: Config) -> None:
    first = Automations(config, Bus())
    await first.start()
    a = await first.create(body())
    await first.update(a.id, {"paused": True})
    path = config.paths.home / "automations.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = Automations(config, Bus())
    await again.start()
    [b] = again.all()
    assert (b.id, b.name, b.paused, b.schedule) == (a.id, "Morning", True, DAILY)


async def test_an_unreadable_file_is_kept_aside(config: Config) -> None:
    path = config.paths.home / "automations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    automations = Automations(config, Bus())
    await automations.start()
    assert automations.all() == []
    assert (config.paths.home / "automations.json.broken").read_text() == "{not json"


async def test_start_over_backs_up_and_clears_the_automations(daemon: Daemon) -> None:
    use(daemon)
    await daemon.automations.create(body())
    async with client(daemon) as http:
        answer = (await http.post("/api/reset", json={"level": "everything"})).json()
        after = (await http.get("/api/automations")).json()["automations"]
        assert "automations.json" in answer["backup"]["files"]
        assert "automations" in answer["message"]
        assert after == []
        saved = daemon.config.paths.home / "backups" / answer["backup"]["id"] / "automations.json"
        assert json.loads(saved.read_text())["automations"][0]["name"] == "Morning"
        restored = (await http.post(f"/api/backups/{answer['backup']['id']}/restore")).json()
        assert "automations.json" in restored["restored"]
        assert [a["name"] for a in (await http.get("/api/automations")).json()["automations"]] == ["Morning"]


async def test_run_now_is_a_turn_of_its_own(daemon: Daemon) -> None:
    events = daemon.bus.subscribe(
        {AutomationStarted.TYPE, AutomationFinished.TYPE, VisionReply.TYPE, StateChanged.TYPE}
    )
    a = await daemon.automations.create(body("Greeting", schedule={"kind": "daily", "time": "06:00"}))
    async with client(daemon) as http:
        queued = (await http.post(f"/api/automations/{a.id}/run")).json()
        assert queued["queued"] is True
        await until(lambda: bool(a.results), timeout=10)
        state = (await http.get("/api/state")).json()
        history = (await http.get("/api/history")).json()["turns"]
    seen = []
    while len(seen) < 6:
        seen.append(await events.get())
    names = [type(e).__name__ for e in seen]
    assert names[0] == "AutomationStarted" and "AutomationFinished" in names
    finished = next(e for e in seen if isinstance(e, AutomationFinished))
    assert finished.status == "ok" and finished.reply.startswith("I am running on the fake brain")
    result = a.results[-1]
    assert result.status == "ok" and result.trigger == "manual"
    assert a.next_run is not None  # a manual run leaves the schedule alone
    assert state["automation"] is None
    turn = history[-1]
    assert turn["source"] == "automation" and turn["user_text"] == "Read me the weather."
