"""The local-model catalog against this Mac's memory, the tool-call checks, and offline mode
and the local models in Settings, the state and the awareness (on a served daemon)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from settings_fakes import client, use
from test_residents_local import on_disk

from vision.app import Daemon
from vision.brains import catalog
from vision.brains.local_chat import Call
from vision.brains.local_server import Probe
from vision.brains.local_tools import problem
from vision.core.events import BrainMode, Notice
from vision.core.interfaces import ToolSpec
from vision.setup import hf_cache

GB = 1024**3
DEFAULT = "mlx-community/Qwen3-4B-Instruct-2507-4bit"


# ---------------------------------------------------------------- the catalog


def test_the_catalog_is_well_formed() -> None:
    cat = catalog.load_catalog()
    ids = [m.id for m in cat.models]
    assert cat.taken == "2026-11-13" and 8 <= len(ids) <= 12 and len(set(ids)) == len(ids)
    assert DEFAULT in ids and all(i.startswith("mlx-community/") for i in ids)
    assert [m.size_bytes for m in cat.models if m.kind == "general"][0] < 3e9
    assert {m.kind for m in cat.models} == {"general", "code"}
    assert all(m.tools or not m.tools_recommended for m in cat.models)


@pytest.mark.parametrize(
    ("memory_gb", "recommended"),
    [
        (8, "mlx-community/Qwen3.5-4B-MLX-4bit"),
        (16, "mlx-community/Qwen3.5-9B-MLX-4bit"),
        (32, "mlx-community/Qwen3.8-27B-4bit"),
        (64, "mlx-community/Qwen3.6-35B-A3B-4bit"),
        (128, "mlx-community/Qwen3.5-122B-A10B-4bit"),
    ],
)
def test_fit_and_recommendation(memory_gb: int, recommended: str) -> None:
    listing = catalog.listing(memory_gb * GB)
    assert listing["recommended"] == recommended
    fits = {m["id"]: m["fit"] for m in listing["models"]}
    assert fits[recommended] == "comfortable"
    assert fits[DEFAULT] == "comfortable"


def test_tight_and_too_big_on_the_owners_mac() -> None:
    fits = {m["id"]: m["fit"] for m in catalog.listing(64 * GB)["models"]}
    assert fits["mlx-community/Llama-3.3-70B-Instruct-4bit"] == "tight"
    assert fits["mlx-community/gpt-oss-120b-MXFP4-Q8"] == "too_big"
    assert catalog.recommend(catalog.load_catalog(), 4 * GB) is None


def test_small_models_by_size() -> None:
    assert catalog.is_small(DEFAULT, None)
    assert not catalog.is_small("mlx-community/Qwen3.6-35B-A3B-4bit", None)
    assert catalog.is_small("someone/tiny", 1_000_000) and not catalog.is_small("someone/unknown", None)


# ---------------------------------------------------------------- checking a call

SPEC = ToolSpec(
    "remember",
    "Save a note.",
    {
        "type": "object",
        "properties": {"text": {"type": "string"}, "pin": {"type": "boolean"}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


@pytest.mark.parametrize(
    ("call", "wanted"),
    [
        (Call("1", "remember", {"text": "x"}), ""),
        (Call("1", "forget", {}), "there is no tool called 'forget'; the tools are: remember"),
        (Call("1", "remember", {}), "remember needs text"),
        (Call("1", "remember", {"text": "x", "colour": "red"}), "remember takes no colour; it takes text, pin"),
        (Call("1", "remember", {"text": 3}), "text must be a string"),
        (Call("1", "remember", {"text": "x", "pin": "yes"}), "pin must be a boolean"),
        (Call("1", "", {}, "it could not be read (bad)"), "it could not be read (bad)"),
    ],
)
def test_a_call_is_checked_before_it_runs(call: Call, wanted: str) -> None:
    assert problem(call, [SPEC]) == wanted


# ---------------------------------------------------------------- settings and state


def hub() -> Path:
    return hf_cache.hub_cache()


async def test_listing_marks_this_mac_and_the_disk(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.memory = 16 * GB
    fake.cache[DEFAULT] = 2_300_000_000
    async with client(daemon) as http:
        got = (await http.get("/api/local-models")).json()
    assert got["memory_bytes"] == 16 * GB and got["recommended"] == "mlx-community/Qwen3.5-9B-MLX-4bit"
    assert got["chosen"] == {"backend": "mlx", "model": DEFAULT, "server": daemon.config.brain.local_base_url, "tools": None}
    assert got["offline"] is False and got["custom"] is None and got["taken"] == "2026-11-13"
    row = next(m for m in got["models"] if m["id"] == DEFAULT)
    assert row["on_disk_bytes"] == 2_300_000_000 and row["download"]["state"] == "done"
    assert set(row) >= {"title", "good_at", "params_b", "size_bytes", "memory_gb", "context", "tools", "tools_recommended", "license", "fit"}
    big = next(m for m in got["models"] if m["id"] == "mlx-community/Qwen3.6-35B-A3B-4bit")
    assert big["fit"] == "too_big" and big["on_disk_bytes"] is None and big["download"]["state"] == "idle"


async def test_download_and_delete(daemon: Daemon) -> None:
    fake = use(daemon)
    repo = "mlx-community/Qwen3-8B-4bit"
    async with client(daemon) as http:
        started = await http.post("/api/local-models/download", json={"repo": repo})
        bad = await http.post("/api/local-models/download", json={"repo": "../etc"})
        assert started.status_code == 200 and bad.status_code == 400
        for _ in range(100):
            if repo in fake.cache:
                break
            await asyncio.sleep(0.02)
        row = next(m for m in (await http.get("/api/local-models")).json()["models"] if m["id"] == repo)
        assert row["download"]["state"] == "done" and f"download {repo}" in fake.calls
        deleted = (await http.post("/api/local-models/delete", json={"repo": repo})).json()
    assert deleted["deleted"] == repo and deleted["freed_bytes"] == 1 and repo not in fake.cache


async def test_the_model_offline_mode_uses_cannot_be_deleted(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.cache[DEFAULT] = 1
    daemon.config.brain.offline = True
    async with client(daemon) as http:
        refused = await http.post("/api/local-models/delete", json={"repo": DEFAULT})
    assert refused.status_code == 400 and "offline mode is using" in refused.json()["detail"]


async def test_server_test(daemon: Daemon) -> None:
    fake = use(daemon)
    async with client(daemon) as http:
        ok = (await http.post("/api/local-models/server/test", json={"server": "http://127.0.0.1:1234/v1"})).json()
        bad = await http.post("/api/local-models/server/test", json={"server": "ftp://x"})
    assert ok == {"ok": True, "models": ["llama3.2"], "message": "The server answers."}
    assert fake.calls[-1] == "probe http://127.0.0.1:1234/v1" and bad.status_code == 400


async def test_offline_needs_a_downloaded_model(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        refused = await http.patch("/api/settings", json={"models": {"offline": True}})
    error = refused.json()["detail"]["errors"][0]
    assert refused.status_code == 400 and error["field"] == "models.offline"
    assert "is not downloaded yet" in error["message"] and daemon.config.brain.offline is False


async def test_offline_on_and_off_while_running(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.cache[DEFAULT] = 2_300_000_000
    seen = daemon.bus.subscribe({BrainMode.TYPE, Notice.TYPE})
    async with client(daemon) as http:
        on = (await http.patch("/api/settings", json={"models": {"offline": True}})).json()
        state = (await http.get("/api/state")).json()
        off = (await http.patch("/api/settings", json={"models": {"offline": False}})).json()
    assert on["applied"] == ["models.offline"] and on["restart"] == []
    assert on["settings"]["models"]["local"]["offline"] is True
    assert state["mode"] == {
        "offline": True,
        "answering": "fake",
        "local_backend": "mlx",
        "local_model": DEFAULT,
        "local_tools": None,
    }
    assert off["settings"]["models"]["local"]["offline"] is False and daemon.config.brain.offline is False
    events: list[Any] = []
    while not seen._queue.empty():  # noqa: SLF001
        events.append(seen._queue.get_nowait())  # noqa: SLF001
    modes = [e for e in events if isinstance(e, BrainMode)]
    notices = [e.text for e in events if isinstance(e, Notice)]
    assert [m.offline for m in modes] == [True, False]
    assert any(t.startswith("Offline mode is on") for t in notices)
    assert any(t.startswith("Offline mode is off") for t in notices)


async def test_the_server_backend_is_checked_too(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.server = Probe(True, ["qwen3:8b"], "ok")
    async with client(daemon) as http:
        wrong = await http.patch(
            "/api/settings",
            json={"models": {"offline": True, "local_backend": "openai", "local": "llama3.2", "local_server": "http://127.0.0.1:11434/v1"}},
        )
        right = await http.patch(
            "/api/settings",
            json={"models": {"offline": True, "local_backend": "openai", "local": "qwen3:8b"}},
        )
        mlx_name = await http.patch("/api/settings", json={"models": {"local_backend": "mlx", "local": "qwen3:8b"}})
    assert wrong.status_code == 400 and "has no model called llama3.2" in wrong.json()["detail"]["errors"][0]["message"]
    assert right.status_code == 200 and daemon.config.brain.local_model == "qwen3:8b"
    assert daemon.config.brain.local_backend == "openai" and daemon.local.backend == "openai"
    assert mlx_name.status_code == 400 and "Hugging Face repo" in mlx_name.json()["detail"]["errors"][0]["message"]


async def test_awareness_tells_the_truth_offline(daemon: Daemon) -> None:
    daemon.config.brain.offline = True
    summary = daemon.awareness.summary()
    assert f"Offline mode is on: you and the residents run on the local model {DEFAULT}" in summary
    assert "Web search and loading web pages are not available" in summary


def test_delete_stays_inside_the_cache(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        hf_cache.delete("../../etc", tmp_path)
    on_disk(DEFAULT)
    assert hf_cache.delete(DEFAULT) == 10 and hf_cache.cached_size(DEFAULT) is None
