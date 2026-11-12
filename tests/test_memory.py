"""Memory: vault, log, search and the core, on a temp `VISION_HOME`."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from vision.core.config import Config, load_config
from vision.core.interfaces import AuditRecord, Memory, TurnRecord
from vision.memory import make_memory
from vision.memory.vault import bundled_template


def turn(n: int, user: str = "hello", reply: str = "hi", started: float | None = None) -> TurnRecord:
    t = started if started is not None else 1000.0 + n
    return TurnRecord(f"t{n}", t, t + 1, "text", user, reply, "ok", "fake", "fake-1", 3, 4)


@pytest.fixture
async def mem(config: Config) -> AsyncIterator[Memory]:
    m = make_memory(config)
    await m.start()
    yield m
    await m.close()


def test_factory_does_no_io(config: Config) -> None:
    m = make_memory(config)
    assert isinstance(m, Memory)
    assert not config.paths.house.exists()
    assert not config.paths.log_db.exists()


async def test_start_seeds_templates_without_overwriting(config: Config) -> None:
    readme = config.paths.house / "library" / "README.md"
    persona = config.paths.house / "agents" / "host.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("my own readme")
    m = make_memory(config)
    await m.start()
    await m.close()
    assert readme.read_text() == "my own readme"
    assert persona.read_text() == bundled_template("agents/host.md")
    assert (config.paths.house / "notes").is_dir()

    persona.write_text("edited persona")
    m = make_memory(config)
    await m.start()
    await m.close()
    assert persona.read_text() == "edited persona"


async def test_notes_survive_restart(config: Config) -> None:
    m = make_memory(config)
    await m.start()
    await m.remember("The garage code is four seven one one.")
    await m.close()

    again = make_memory(config)
    await again.start()
    hits = await again.recall("garage code")
    await again.close()
    assert [h.kind for h in hits] == ["note"]
    assert "garage code" in hits[0].text
    assert hits[0].ref.startswith("notes/") and hits[0].ref.endswith(".md")


async def test_remember_writes_dated_timestamped_markdown(mem: Memory, config: Config) -> None:
    await mem.remember("First thing.")
    await mem.remember("Second thing.")
    (file,) = (config.paths.house / "notes").glob("*.md")
    assert file.stem == time.strftime("%Y-%m-%d")
    body = file.read_text()
    assert body.count("## ") == 2
    assert "First thing." in body and "Second thing." in body


async def test_blank_note_is_ignored(mem: Memory, config: Config) -> None:
    await mem.remember("   ")
    assert list((config.paths.house / "notes").glob("*.md")) == []


async def test_recall_ranks_exact_above_loose_and_finds_turns(mem: Memory) -> None:
    await mem.remember("Dentist appointment on Tuesday at nine.")
    await mem.remember("Remember to call the dentist someday.")
    await mem.log_turn(turn(1, "when is my dentist appointment on tuesday", "Tuesday at nine."))
    await mem.log_turn(turn(2, "what is the weather", "Sunny."))

    hits = await mem.recall("dentist appointment tuesday", limit=5)
    kinds = {h.kind for h in hits}
    assert kinds == {"note", "turn"}
    notes = [h for h in hits if h.kind == "note"]
    assert "Tuesday" in notes[0].text
    assert notes[0].score > notes[1].score
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    assert [h.ref for h in hits if h.kind == "turn"] == ["t1"]


async def test_recall_limit_and_odd_queries(mem: Memory) -> None:
    for i in range(4):
        await mem.remember(f"note {i} about gardening")
    assert len(await mem.recall("gardening", limit=2)) == 2
    assert await mem.recall("") == []
    assert await mem.recall('"( OR NEAR* )"') == []
    assert await mem.recall("gardening AND (", limit=1)


async def test_recall_snippet_is_trimmed_for_long_notes(mem: Memory) -> None:
    await mem.remember("alpha " * 200 + "needle " + "omega " * 200)
    (hit,) = await mem.recall("needle")
    assert "needle" in hit.text
    assert len(hit.text) < 400


async def test_hand_edit_and_delete_change_recall(mem: Memory, config: Config) -> None:
    await mem.remember("The wifi password is hunter2.")
    assert await mem.recall("hunter2")
    (file,) = (config.paths.house / "notes").glob("*.md")

    file.write_text(file.read_text().replace("hunter2", "swordfish-and-more"))
    assert await mem.recall("hunter2") == []
    assert len(await mem.recall("swordfish")) == 1

    handwritten = config.paths.house / "notes" / "2020-01-02.md"
    handwritten.write_text("Plain text with no heading about zeppelins.")
    (hit,) = await mem.recall("zeppelins")
    assert hit.ref == "notes/2020-01-02.md"
    assert time.strftime("%Y", time.localtime(hit.ts)) == "2020"

    file.unlink()
    handwritten.unlink()
    assert await mem.recall("swordfish") == []
    assert await mem.recall("zeppelins") == []


async def test_history_order_and_limit(mem: Memory) -> None:
    for n in (3, 1, 2, 5, 4):
        await mem.log_turn(turn(n))
    assert [t.turn_id for t in await mem.history()] == ["t1", "t2", "t3", "t4", "t5"]
    assert [t.turn_id for t in await mem.history(limit=2)] == ["t4", "t5"]
    assert await mem.history(limit=0) == []
    first = (await mem.history(limit=5))[0]
    assert first == turn(1)


async def test_turn_with_same_id_is_replaced(mem: Memory) -> None:
    await mem.log_turn(turn(1, "old words", "x"))
    await mem.log_turn(turn(1, "new words", "y"))
    assert [t.user_text for t in await mem.history()] == ["new words"]
    assert await mem.recall("old") == []
    assert len(await mem.recall("new")) == 1


async def test_audit_round_trip(mem: Memory, config: Config) -> None:
    entry = AuditRecord(
        ts=5.0,
        tool="shell",
        args={"command": "ls", "n": [1, 2]},
        tier="ask",
        decision="allow",
        result="ok",
        request_id="r1",
    )
    await mem.audit(entry)
    await mem.close()
    db = sqlite3.connect(config.paths.log_db)
    (row,) = db.execute("SELECT ts, tool, args, tier, decision, result, request_id FROM audit")
    db.close()
    assert row == (5.0, "shell", '{"command": "ls", "n": [1, 2]}', "ask", "allow", "ok", "r1")


async def test_log_uses_wal(mem: Memory, config: Config) -> None:
    db = sqlite3.connect(config.paths.log_db)
    assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    db.close()


async def test_concurrent_writes_do_not_corrupt(mem: Memory, config: Config) -> None:
    await asyncio.gather(
        *(mem.log_turn(turn(n, f"question {n}", "answer")) for n in range(60)),
        *(mem.remember(f"concurrent note {n}") for n in range(20)),
        *(
            mem.audit(AuditRecord(float(n), "t", {}, "free", "allow", "ok"))
            for n in range(20)
        ),
    )
    assert len(await mem.history(limit=100)) == 60
    assert len(await mem.recall("concurrent", limit=50)) == 20
    await mem.close()
    db = sqlite3.connect(config.paths.log_db)
    assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert db.execute("SELECT COUNT(*) FROM audit").fetchone() == (20,)
    db.close()


async def test_use_before_start_fails_clearly(config: Config) -> None:
    with pytest.raises(RuntimeError, match="start"):
        await make_memory(config).history()


def config_with(home: Path, **paths: object) -> Config:
    home.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(f"{k} = {v!r}" for k, v in paths.items()).replace("'", '"')
    (home / "config.toml").write_text(f"[paths]\n{lines}\n")
    return load_config(home)
