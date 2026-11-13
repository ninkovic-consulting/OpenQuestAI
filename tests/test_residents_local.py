"""Residents on the local model: offline jobs through the same board and gate, refusals
when the local model cannot take work, the fallback when Claude cannot be used, and a
Claude job that stops once offline mode is turned on. No model is loaded."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scheduler_fakes import until
from test_brains_mlx import END, START, StubModel, StubRuntime, engine_on
from test_residents import Client, World, seeded, text, use  # noqa: F401 - `seeded` is a fixture

from vision.brains.engine import LocalEngine
from vision.core.config import Config
from vision.jobs import JobError
from vision.residents import BUDGET_USED, NO_KEY
from vision.residents.worker import OFFLINE_STOPPED


def on_disk(repo: str) -> None:
    """A downloaded model in the test's Hugging Face cache (`HF_HUB_CACHE`)."""
    import os

    snap = Path(os.environ["HF_HUB_CACHE"]) / f"models--{repo.replace('/', '--')}" / "snapshots" / "abc"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "model.safetensors").write_bytes(b"\0" * 10)


def call(name: str, **args: Any) -> list[str]:
    return [START, json.dumps({"name": name, "arguments": args}), END]


def local_world(config: Config, model: StubModel, client: Client | None = None) -> tuple[World, LocalEngine]:
    w = World(config, client)
    engine = engine_on(config, StubRuntime(model))
    w.residents._local = engine  # noqa: SLF001 - the daemon passes it in; the World builds without
    return w, engine


async def test_offline_job_runs_locally_through_the_gate(seeded: Config) -> None:
    seeded.brain.offline = True
    on_disk(seeded.brain.local_model)
    model = StubModel([call("remember", text="The project uses pytest."), ["It is a calculator."]])
    client = Client([])
    w, engine = local_world(seeded, model, client)
    job = await w.run("Tink", "Explain the project.")
    assert job.status == "done" and job.result == "It is a calculator."
    assert job.local is True and job.model == seeded.brain.local_model and job.cost_usd == 0
    assert client.requests == [] and w.budget.spent_usd == 0  # nothing went to Anthropic
    assert job.steps[1].text == "Save a note: The project uses pytest."
    audit = w.memory.audits[-1]
    assert (audit.tool, audit.agent, audit.job, audit.decision) == ("remember", "maker", job.id, "allow")
    assert "Web search and loading web pages are not available" in model.prompts[0] and "offline mode" in model.prompts[0]
    assert model.offered[0] == ["remember", "recall", "note_progress", "ask_resident", "list_documents", "read_document", "search_documents"]
    await engine.close()


async def test_offline_refuses_work_when_the_model_is_missing_or_talk_only(seeded: Config) -> None:
    seeded.brain.offline = True
    w, engine = local_world(seeded, StubModel([["x"]], tools=False))
    await w.board.start(w.residents)
    with pytest.raises(JobError, match="Offline mode is on.*No local model is downloaded on this Mac"):
        await w.board.hand_off("Tink", "Build it.")
    on_disk(seeded.brain.local_model)
    with pytest.raises(JobError, match="cannot use tools, so the residents cannot work on it"):
        await w.board.hand_off("Tink", "Build it.")
    await engine.close()


async def test_a_spent_budget_falls_back_to_the_local_model(seeded: Config) -> None:
    on_disk(seeded.brain.local_model)
    model = StubModel([["Done locally."]])
    client = Client([text("never")])
    w, engine = local_world(seeded, model, client)
    w.budget.set_cap(0.0)
    job = await w.run("Tock", "Check it.")
    assert job.status == "done" and job.result == "Done locally." and job.local
    assert client.requests == []
    assert "because the main model is not available right now" in model.prompts[0]
    await engine.close()


async def test_without_a_usable_local_model_the_old_refusals_stand(seeded: Config) -> None:
    w, engine = local_world(seeded, StubModel([["x"]]), None)
    keyless = await w.run("Tink", "x")
    assert keyless.status == "failed" and keyless.error == NO_KEY
    w.budget.set_cap(0.0)
    with pytest.raises(JobError) as refused:
        await w.board.hand_off("Tink", "x")
    assert str(refused.value) == BUDGET_USED
    await engine.close()


async def test_a_claude_job_stops_when_offline_mode_is_turned_on(seeded: Config) -> None:
    client = Client([use("note_progress", text="half"), text("never")])
    w = World(seeded, client)
    seeded.gate.tiers["note_progress"] = "free"
    real_stream = client._stream

    def stream(**kwargs: Any) -> Any:
        seeded.brain.offline = True  # switched on while the first call runs
        return real_stream(**kwargs)

    client.beta.messages.stream = stream
    await w.board.start(w.residents)
    job = await w.board.hand_off("Tink", "Work.")
    await until(lambda: not job.open, timeout=10)
    assert job.status == "failed" and job.error == OFFLINE_STOPPED
    assert len(client.requests) == 1 and job.local is False and job.model == "claude-sonnet-5-5"
