"""GET and PATCH /api/settings through the real server, with the outside world faked."""

from __future__ import annotations

import asyncio
import tomllib

import pytest
from settings_fakes import client, service, use

from vision.app import Daemon
from vision.core.events import BudgetUpdate, HouseChanged

ROUTES = [
    ("GET", "/api/settings"),
    ("PATCH", "/api/settings"),
    ("POST", "/api/settings/key"),
    ("POST", "/api/settings/key/verify"),
    ("GET", "/api/models"),
    ("GET", "/api/voice/devices"),
    ("POST", "/api/voice"),
    ("POST", "/api/voice/test"),
    ("GET", "/api/downloads"),
    ("POST", "/api/downloads"),
    ("GET", "/api/fs/dirs?prefix=~/"),
    ("GET", "/api/doctor"),
    ("POST", "/api/doctor/fix"),
    ("POST", "/api/reset"),
    ("GET", "/api/backups"),
    ("POST", "/api/backups/20261112-130500-settings/restore"),
]


def config_file(d: Daemon) -> dict:
    with d.config.paths.config_file.open("rb") as fh:
        return tomllib.load(fh)


@pytest.mark.parametrize(("method", "path"), ROUTES)
async def test_every_route_needs_the_token(daemon: Daemon, method: str, path: str) -> None:
    fake = use(daemon)
    async with client(daemon, token=False) as http:
        answer = await http.request(method, path, json={})
    assert answer.status_code == 401
    assert fake.calls == []


async def test_settings_shape(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        got = (await http.get("/api/settings")).json()
    assert set(got) == {
        "assistant", "owner", "models", "budget", "agents", "voice", "gate", "jobs", "projects", "key",
        "setup", "restart_pending",
    }
    assert got["owner"] == {"name": "", "business": "", "notes": ""}
    assert got["jobs"] == {
        "max_running": 2, "max_steps": 24, "timeout_s": 900.0, "max_job_usd": 1.0, "speak_results": True,
    }
    assert got["assistant"] == {"name": "Vision"}
    assert got["models"]["talk"] == "claude-haiku-5-5"
    assert got["models"]["local"]["downloaded"] is False
    assert got["budget"]["cap_usd"] == 150.0 and got["budget"]["warn_fraction"] == 0.8
    host = got["agents"][0]
    assert host["id"] == "host" and host["is_host"] and host["name"] == "Vision"
    assert not any(a["is_host"] for a in got["agents"][1:])
    assert got["gate"]["never_free"] == ["start_project"]
    assert got["projects"] == {"root": "~/Projects"}
    assert got["gate"]["free_at_the_mac_only"] == ["shell"]
    assert got["gate"]["free_for_jobs_from_the_mac"] == ["run_program"]
    assert got["gate"]["tiers"]["run_program"] == "ask" and got["gate"]["tiers"]["read_file"] == "free"
    assert got["gate"]["tiers"]["shell"] == "ask"
    assert {t["id"] for t in got["gate"]["tools"]} >= {"remember", "shell"}
    assert got["gate"]["tools"][4] == {
        "id": "shell",
        "title": "Shell",
        "description": "Runs a shell command on this Mac, after asking you unless you make it free.",
    }
    assert got["gate"]["tools"][5]["id"] == "run_program"  # right after Shell, in Asking first
    assert [t["id"] for t in got["gate"]["tools"]].count("run_program") == 1
    assert got["gate"]["tiers"]["delete_automation"] == "ask"
    assert got["gate"]["tiers"]["create_automation"] == "free"
    assert got["key"] == {"stored": False, "source": None}
    assert got["setup"] == {"completed": False, "first_run": True}
    assert got["restart_pending"] == []
    voice = got["voice"]
    assert voice["running"] is True and voice["mic"] == "granted" and voice["mic_detail"] is None
    assert voice["tts_voice"] == "af_heart" and voice["models_downloaded"] is False


async def test_validation_lists_every_problem_and_writes_nothing(daemon: Daemon) -> None:
    use(daemon)
    body = {
        "assistant": {"name": "Ada"},
        "budget": {"cap_usd": -1},
        "voice": {"tts_voice": "robot", "followup_s": 900},
        "models": {"talk": "not a model!"},
        "setup": {"completed": "yes"},
        "colour": {},
    }
    async with client(daemon) as http:
        answer = await http.patch("/api/settings", json=body)
    assert answer.status_code == 400
    errors = {e["field"]: e["message"] for e in answer.json()["detail"]["errors"]}
    assert errors["budget.cap_usd"] == "The monthly cap must be a number of dollars, 0 or more."
    assert errors["voice.tts_voice"].startswith("The voice must be one of: af_heart")
    assert "0 to 300" in errors["voice.followup_s"]
    assert "claude-opus-5-5" in errors["models.talk"]
    assert errors["setup.completed"] == "Send true or false."
    assert "colour" in errors
    assert daemon.config.assistant.name == "Vision"
    assert not daemon.config.paths.config_file.exists()


async def test_cap_rejects_booleans_and_text(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        for bad in (True, "100", None):
            answer = await http.patch("/api/settings", json={"budget": {"cap_usd": bad}})
            assert answer.status_code == 400


async def test_shell_and_run_program_can_be_free_but_start_project_never(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        project = await http.patch("/api/settings", json={"gate": {"tiers": {"start_project": "free"}}})
        assert project.status_code == 400
        [error] = project.json()["detail"]["errors"]
        assert error["field"] == "gate.tiers.start_project"
        assert "never free" in error["message"]
        unknown = await http.patch("/api/settings", json={"gate": {"tiers": {"rm": "free"}}})
        assert unknown.status_code == 400
        bad = await http.patch("/api/settings", json={"gate": {"tiers": {"recall": "maybe"}}})
        assert bad.json()["detail"]["errors"][0]["message"] == "A tier is free, ask or never."
        shell = await http.patch("/api/settings", json={"gate": {"tiers": {"shell": "free"}}})
        assert daemon.config.gate.tiers["run_program"] == "ask"
        program = await http.patch("/api/settings", json={"gate": {"tiers": {"run_program": "free"}}})
    assert shell.status_code == 200 and shell.json()["applied"] == ["gate.tiers.shell"]
    assert program.status_code == 200 and program.json()["applied"] == ["gate.tiers.run_program"]
    assert program.json()["settings"]["gate"]["tiers"]["run_program"] == "free"
    assert daemon.config.gate.tiers["shell"] == "free"
    assert daemon.config.gate.tiers["run_program"] == "free"
    assert daemon.config.gate.tiers["start_project"] == "ask"
    assert config_file(daemon)["gate"]["tiers"] == {"shell": "free", "run_program": "free"}


async def test_gate_tiers_apply_at_once(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.patch(
            "/api/settings", json={"gate": {"tiers": {"open_url": "never", "shell": "never"}}}
        )
    assert answer.status_code == 200
    got = answer.json()
    assert got["changed"] == got["applied"] == ["gate.tiers.open_url", "gate.tiers.shell"]
    assert got["restart"] == []
    assert got["settings"]["gate"]["tiers"]["open_url"] == "never"
    assert config_file(daemon)["gate"]["tiers"] == {"open_url": "never", "shell": "never"}
    result = await daemon.components.tools.call("open_url", {"url": "https://example.com"})
    assert not result.ok


async def test_assistant_name_applies_to_the_house(daemon: Daemon) -> None:
    use(daemon)
    changes = daemon.bus.subscribe([HouseChanged.TYPE])
    async with client(daemon) as http:
        answer = await http.patch("/api/settings", json={"assistant": {"name": "  Ada  "}})
        plan = (await http.get("/api/house")).json()
    assert answer.json()["applied"] == ["assistant.name"]
    assert answer.json()["settings"]["assistant"]["name"] == "Ada"
    assert isinstance(await asyncio.wait_for(changes.get(), 2), HouseChanged)
    assert plan["assistant"]["name"] == "Ada"
    assert plan["agents"][0]["name"] == "Ada"
    assert config_file(daemon)["assistant"]["name"] == "Ada"


async def test_monthly_cap_applies_and_publishes(daemon: Daemon) -> None:
    use(daemon)
    updates = daemon.bus.subscribe([BudgetUpdate.TYPE])
    async with client(daemon) as http:
        answer = await http.patch("/api/settings", json={"budget": {"cap_usd": 42}})
    assert answer.json()["applied"] == ["budget.cap_usd"]
    event = await asyncio.wait_for(updates.get(), 2)
    assert isinstance(event, BudgetUpdate) and event.cap_usd == 42.0
    assert daemon.components.budget.status().cap_usd == 42.0
    assert config_file(daemon)["budget"]["monthly_cap_usd"] == 42.0


async def test_models_need_a_restart(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.patch(
            "/api/settings",
            json={
                "models": {
                    "talk": "claude-sonnet-5-5",
                    "local": "mlx-community/Qwen3-8B-4bit",
                    "heavy": "claude-opus-5-5",
                }
            },
        )
        got = answer.json()
        again = (await http.get("/api/settings")).json()
    assert got["changed"] == ["models.talk", "models.local"]
    assert got["restart"] == ["models.talk"] and got["applied"] == ["models.local"]
    assert again["restart_pending"] == ["models.talk"]
    assert daemon.config.brain.local_model == "mlx-community/Qwen3-8B-4bit", "the local model follows at once"
    assert again["models"]["talk"] == "claude-sonnet-5-5"
    assert daemon.config.brain.talk_model == "claude-haiku-5-5", "the brain keeps its model"
    assert config_file(daemon)["brain"] == {
        "talk_model": "claude-sonnet-5-5",
        "local_model": "mlx-community/Qwen3-8B-4bit",
        "heavy_model": "claude-opus-5-5",
    }


async def test_bad_local_model_repo(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.patch("/api/settings", json={"models": {"local": "qwen"}})
    assert "Hugging Face repo" in answer.json()["detail"]["errors"][0]["message"]


async def test_agents_go_to_the_house_file(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.patch(
            "/api/settings",
            json={"agents": {"maker": {"name": "Gadget", "model": "claude-sonnet-5-5"}}},
        )
        plan = (await http.get("/api/house")).json()
    assert answer.status_code == 200
    assert answer.json()["applied"] == ["agents.maker.name", "agents.maker.model"]
    maker = next(a for a in plan["agents"] if a["id"] == "maker")
    assert maker["name"] == "Gadget" and maker["model"] == "claude-sonnet-5-5"
    with daemon.config.paths.house_file.open("rb") as fh:
        house = tomllib.load(fh)
    assert house["agents"]["maker"]["name"] == "Gadget"
    assert house["agents"]["maker"]["model"] == "claude-sonnet-5-5"
    assert not daemon.config.paths.config_file.exists()


async def test_host_name_and_model_are_refused(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.patch(
            "/api/settings",
            json={"agents": {"host": {"name": "Boss", "model": "claude-opus-5-5"}, "nope": {}}},
        )
    errors = {e["field"]: e["message"] for e in answer.json()["detail"]["errors"]}
    assert "assistant's name" in errors["agents.host.name"]
    assert "talk model" in errors["agents.host.model"]
    assert "no agent" in errors["agents.nope"]


async def test_voice_settings_restart_running_voice(daemon: Daemon) -> None:
    use(daemon)
    before = daemon.components.voice
    async with client(daemon) as http:
        answer = await http.patch(
            "/api/settings",
            json={"voice": {"tts_voice": "bm_george", "followup_s": 12, "input_device": "USB"}},
        )
    got = answer.json()
    assert got["applied"] == ["voice.tts_voice", "voice.followup_s", "voice.input_device"]
    assert got["settings"]["voice"]["tts_voice"] == "bm_george"
    assert got["settings"]["voice"]["followup_s"] == 12.0
    assert daemon.components.voice is not before and daemon.voice_running
    assert daemon.session is not None and daemon.session.speaker is daemon.components.voice.speaker
    assert config_file(daemon)["voice"] == {
        "tts_voice": "bm_george",
        "followup_window_s": 12.0,
        "input_device": "USB",
    }


async def test_setup_completed(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.key = "sk-ant-x"
    async with client(daemon) as http:
        answer = await http.patch("/api/settings", json={"setup": {"completed": True}})
    assert answer.json()["settings"]["setup"] == {"completed": True, "first_run": False}
    assert config_file(daemon)["assistant"] == {"setup_completed": True}


async def test_unchanged_values_are_not_reported(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.patch("/api/settings", json={"assistant": {"name": "Vision"}})
    assert answer.json()["changed"] == []
    settings = service(daemon)
    assert settings.restart_pending(settings.saved()) == []


async def test_body_must_be_an_object(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        answer = await http.patch("/api/settings", content=b"[1, 2]")
        broken = await http.patch("/api/settings", content=b"{nope")
    assert answer.status_code == broken.status_code == 400
