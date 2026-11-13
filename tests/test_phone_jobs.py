"""The phone and the residents: job reports by their choice, and `run_program`, which
the phone does not approve until the owner adds it."""

from __future__ import annotations

import json
import time

from phone_fakes import CHAT, rig
from settings_fakes import client

from vision.app import Daemon
from vision.core.events import GateRequest
from vision.remote import store
from vision.remote.store import PhoneState


def program_request() -> GateRequest:
    return GateRequest(
        id="r9",
        tool="run_program",
        summary="Tock, in the Spare Room: run a program",
        detail="Run this command:\n/usr/bin/python3 -m pytest -q",
        expires_at=time.time() + 60,
        agent="checker",
        agent_name="Tock",
        job="j1",
    )


async def test_a_job_from_the_phone_reports_there_unless_never() -> None:
    r = rig()
    await r.channel.notifier.job_result("j1", "Tock ran the tests: test_b fails.", from_phone=True, started_at=0.0)
    assert r.transport.sent == [(CHAT, "Tock ran the tests: test_b fails.")]
    r.state.notify_jobs = "never"
    await r.channel.notifier.job_result("j2", "Again.", from_phone=True, started_at=0.0)
    assert len(r.transport.sent) == 1
    unpaired = rig(paired=False)
    await unpaired.channel.notifier.job_result("j3", "Nobody to tell.", from_phone=True, started_at=0.0)
    assert unpaired.transport.sent == []


async def test_run_program_waits_for_the_mac_by_default() -> None:
    r = rig()
    req = program_request()
    r.host.pending[req.id] = req
    await r.channel.notifier.handle(req)
    assert r.transport.buttons == []
    assert "Tock, in the Spare Room: run a program" in r.transport.texts()[0]
    assert "not one of the tools the phone may approve" in r.transport.texts()[0]


async def test_the_owner_can_let_the_phone_approve_run_program() -> None:
    r = rig()
    r.state.phone_tools = ["run_program"]
    req = program_request()
    r.host.pending[req.id] = req
    await r.channel.notifier.handle(req)
    assert [b.label for b in r.transport.buttons[0][2]] == ["Yes", "Not now"]


def test_an_older_phone_file_does_not_list_run_program(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "phone.json"
    path.write_text(json.dumps({"version": 1, "phone": {"phone_tools": ["remember", "open_url"]}}))
    assert "run_program" not in (store.load(path).phone_tools or [])
    assert PhoneState().phone_tools is None


async def test_settings_list_run_program_off_and_shell_impossible(daemon: Daemon) -> None:
    async with client(daemon) as http:
        view = (await http.get("/api/phone")).json()
        tools = [t["id"] for t in view["tools"]]
        assert "run_program" in tools and "write_file" in tools
        assert "run_program" not in view["phone_tools"] and "write_file" in view["phone_tools"]
        assert view["mac_only"] == ["shell"] and view["notify"]["jobs"] == "always"
        allowed = (await http.patch("/api/phone", json={"phone_tools": ["run_program", "edit_file"]})).json()
        assert set(allowed["phone_tools"]) == {"edit_file", "run_program"}
        quiet = (await http.patch("/api/phone", json={"notify": {"jobs": "never"}})).json()
        assert quiet["notify"]["jobs"] == "never"
        shell = await http.patch("/api/phone", json={"phone_tools": ["shell"]})
    assert shell.status_code == 400
