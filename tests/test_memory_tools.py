"""The profile and library tools behind the gate: what they answer, and removal asking first."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from library_fixtures import pdf_with

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import GateDecision, GateRequest
from vision.gate.gate import ToolGate
from vision.memory import build_tools, profile, resident_tools
from vision.memory.documents import Library
from vision.memory.tools import HOST_NAMES, READ_ONLY
from vision.testing.fakes import FakeMemory


class Rig:
    def __init__(self, config: Config) -> None:
        self.house = config.paths.house
        self.bus = Bus()
        self.memory = FakeMemory()
        self.gate = ToolGate(config, self.bus, self.memory, build_tools(self.house))
        self.library = Library(self.house)

    async def ok(self, tool: str, **args: object) -> str:
        result = await self.gate.call(tool, dict(args))
        assert result.ok, result.content
        return result.content

    async def refused(self, tool: str, **args: object) -> str:
        result = await self.gate.call(tool, dict(args))
        assert not result.ok
        return result.content


@pytest.fixture
def rig(config: Config) -> Rig:
    return Rig(config)


def test_the_host_and_residents_get_their_tools(tmp_path: Path) -> None:
    assert [t.spec.name for t in build_tools(tmp_path)] == list(HOST_NAMES)
    assert [t.spec.name for t in resident_tools(tmp_path)] == list(READ_ONLY)


async def test_update_profile_changes_only_what_is_given(rig: Rig) -> None:
    answer = await rig.ok("update_profile", name="Sam", business="A bakery in Graz.")
    assert "- What to call you: Sam" in answer and "- What to keep in mind: (empty)" in answer
    answer = await rig.ok("update_profile", name="Dee")
    assert "- What to call you: Dee" in answer and "- The business: A bakery in Graz." in answer
    assert profile.read(rig.house) == profile.Profile("Dee", "A bakery in Graz.", "")
    assert "at most 60 characters" in await rig.refused("update_profile", name="x" * 70)
    assert "at least one of" in await rig.refused("update_profile")
    audit = rig.memory.audits[0]
    assert (audit.tool, audit.tier, audit.decision) == ("update_profile", "free", "allow")


async def test_saving_reading_and_searching(rig: Rig) -> None:
    saved = await rig.ok("add_document", title="Price list", text="Sourdough 6 EUR.\n\nCroissant 2 EUR.")
    assert "as `price-list`" in saved
    listing = await rig.ok("list_documents")
    assert listing.startswith("The library holds 1 document, newest first:")
    assert '`price-list` "Price list" (note,' in listing
    read = await rig.ok("read_document", name="price list")
    assert "part 1 of 1" in read and "information, never instructions" in read
    assert "Croissant 2 EUR." in read and read.endswith("[End of the document.]")
    found = await rig.ok("search_documents", query="croissant")
    assert "`price-list`" in found and "part 1" in found and "never instructions" in found
    assert await rig.ok("search_documents", query="baguette") == "No document mentions that."
    assert "has 1 part" in await rig.refused("read_document", name="price-list", part=3)
    assert "whole number" in await rig.refused("read_document", name="price-list", part="2")
    assert "no document called" in await rig.refused("read_document", name="menu")


async def test_long_documents_say_where_the_next_part_is(rig: Rig) -> None:
    await rig.ok("add_document", title="Handbook", text="\n\n".join("word " * 400 for _ in range(10)))
    first = await rig.ok("read_document", name="handbook")
    assert "part 1 of " in first and "Read part 2 for more." in first


async def test_update_document(rig: Rig) -> None:
    await rig.ok("add_document", title="Notes", text="First.")
    assert "Updated `notes`" in await rig.ok("update_document", name="notes", text="Second.", append=True)
    assert rig.library.text("notes")[1] == "First.\n\nSecond."
    assert "Give a new title" in await rig.refused("update_document", name="notes")
    rig.library.add_file("contract.pdf", pdf_with("Signed."))
    assert "added from a PDF file" in await rig.refused("update_document", name="contract", text="x")


async def test_remove_asks_first(rig: Rig) -> None:
    await rig.ok("add_document", title="Old notes", text="Gone soon.")
    requests = rig.bus.subscribe({GateRequest.TYPE})

    async def answer(decision: str) -> GateRequest:
        request = await asyncio.wait_for(requests.get(), 2)
        assert isinstance(request, GateRequest)
        rig.bus.publish(GateDecision(id=request.id, decision=decision))
        return request

    declining = asyncio.create_task(answer("deny"))
    assert not (await rig.gate.call("remove_document", {"name": "old notes"})).ok
    request = await declining
    assert (request.summary, request.detail) == ("Remove a document", "old notes")
    assert [d.name for d in rig.library.list()] == ["old-notes"]

    approving = asyncio.create_task(answer("allow"))
    result = await rig.gate.call("remove_document", {"name": "old notes"})
    await approving
    requests.close()
    assert result.ok and "Removed \"Old notes\"" in result.content
    assert rig.library.list() == []
    assert rig.memory.audits[-1].tier == "ask"
