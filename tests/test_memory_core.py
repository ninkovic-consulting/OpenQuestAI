"""The memory core: ordering, budget, persona lookup and caching.

The owner's profile always opens the core; `alone` is the core a persona
makes with an empty profile and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_memory import config_with
from vision.core.config import Config
from vision.memory import make_memory, profile
from vision.memory.vault import bundled_template

EMPTY_OWNER = profile.prompt_text(profile.Profile(), may_update=True)


def alone(persona: str) -> str:
    return f"{EMPTY_OWNER}\n\n{persona}"


async def started(config: Config):  # type: ignore[no-untyped-def]
    m = make_memory(config)
    await m.start()
    return m


def write_note(config: Config, day: str, *notes: tuple[str, str]) -> None:
    body = "".join(f"## {clock}\n\n{text}\n\n" for clock, text in notes)
    (config.paths.house / "notes" / f"{day}.md").write_text(body)


async def test_core_order_persona_library_notes(config: Config) -> None:
    m = await started(config)
    (config.paths.house / "agents" / "host.md").write_text("PERSONA TEXT")
    (config.paths.house / "library" / "about.md").write_text("Likes tea.")
    await m.remember("Bought a kettle.")
    core = m.core()
    await m.close()
    assert core.index("# The owner") < core.index("PERSONA TEXT") < core.index("Likes tea.") < core.index("Bought a kettle.")
    assert "# The owner's library" in core and "# Recent notes" in core
    assert "What to put here" not in core  # the README is not part of the core


async def test_core_without_library_or_notes_is_just_the_persona(config: Config) -> None:
    m = await started(config)
    core = m.core()
    await m.close()
    assert core == alone(bundled_template("agents/host.md").strip())


async def test_core_notes_newest_first_whole_and_within_budget(tmp_path: Path) -> None:
    config = config_with(tmp_path / "h", core_budget_chars=400)
    m = await started(config)
    (config.paths.house / "agents" / "host.md").write_text("Persona.")
    write_note(config, "2026-01-01", ("09:00:00", "Oldest note."))
    write_note(config, "2026-01-02", ("08:00:00", "Big. " + "padding words " * 40))
    write_note(
        config,
        "2026-01-03",
        ("08:00:00", "Middle note."),
        ("18:30:00", "Newest note of that day."),
    )
    core = m.core()
    await m.close()
    assert len(core) <= 400
    assert core.index("Newest note of that day.") < core.index("Middle note.")
    assert "padding" not in core and "Big." not in core  # too big to fit whole, so left out
    assert "Oldest note." not in core  # nothing older than the first note that did not fit
    assert core.endswith("Middle note.")


async def test_core_budget_cuts_old_notes_only(tmp_path: Path) -> None:
    config = config_with(tmp_path / "h", core_budget_chars=300)
    m = await started(config)
    (config.paths.house / "agents" / "host.md").write_text("P")
    for i in range(30):
        write_note(config, f"2026-02-{i + 1:02d}", ("10:00:00", f"Note number {i:02d} text."))
    core = m.core()
    await m.close()
    assert len(core) <= 300
    assert "Note number 29 text." in core
    assert "Note number 00 text." not in core
    lines = [line for line in core.splitlines() if line.startswith("- [")]
    assert all(line.endswith("text.") for line in lines)


async def test_library_cannot_starve_notes(tmp_path: Path) -> None:
    config = config_with(tmp_path / "h", core_budget_chars=500)
    m = await started(config)
    (config.paths.house / "agents" / "host.md").write_text("P")
    (config.paths.house / "library" / "big.md").write_text("word " * 200)
    await m.remember("A fresh note.")
    core = m.core()
    await m.close()
    assert len(core) <= 500
    assert "A fresh note." in core
    assert "word word" not in core


async def test_persona_lookup_order(tmp_path: Path) -> None:
    home = tmp_path / "h"
    config = config_with(home, persona="mine/custom.md")
    m = make_memory(config)  # not started: only the bundled persona exists
    assert m.core() == alone(bundled_template("agents/host.md").strip())

    await m.start()
    assert m.core().removeprefix(EMPTY_OWNER).lstrip().startswith("# Persona")  # seeded house/agents/host.md
    (config.paths.house / "agents" / "host.md").write_text("HOUSE PERSONA")
    assert m.core() == alone("HOUSE PERSONA")

    custom = home / "mine" / "custom.md"
    custom.parent.mkdir()
    custom.write_text("CONFIGURED PERSONA")
    assert m.core() == alone("CONFIGURED PERSONA")

    custom.unlink()
    assert m.core() == alone("HOUSE PERSONA")
    (config.paths.house / "agents" / "host.md").unlink()
    assert m.core() == alone(bundled_template("agents/host.md").strip())
    await m.close()


async def test_absolute_persona_path(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("ABSOLUTE")
    config = config_with(tmp_path / "h", persona=str(elsewhere))
    m = await started(config)
    assert m.core() == alone("ABSOLUTE")
    await m.close()


async def test_core_is_cached_and_follows_changes(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    m = await started(config)
    first = m.core()
    builds = 0
    from vision.memory import core as core_module

    original = core_module.CoreBuilder._build

    def counting(self):  # type: ignore[no-untyped-def]
        nonlocal builds
        builds += 1
        return original(self)

    monkeypatch.setattr(core_module.CoreBuilder, "_build", counting)
    assert m.core() == first and m.core() == first
    assert builds == 0

    await m.remember("Something new.")
    assert "Something new." in m.core()
    assert builds == 1
    m.core()
    assert builds == 1

    (config.paths.house / "library" / "hand.md").write_text("Hand written fact.")
    assert "Hand written fact." in m.core()
    assert builds == 2
    await m.close()
