"""Web work goes to the scout: it loads pages itself (Anthropic's web fetch, with its own tier,
audit and steps), and the host is told to hand web, test and code work off at once."""

from __future__ import annotations

from test_residents import Client, World, message, offered, seeded, text  # noqa: F401 - `seeded` is a fixture

from vision.app import Daemon
from vision.core.config import Config
from vision.jobs.tools import HAND_OFF
from vision.residents.worker import WEB_FETCH_BASIC, WEB_FETCH_DYNAMIC, web_fetch_tool


def test_the_fetch_type_follows_the_model() -> None:
    assert web_fetch_tool("claude-opus-5-5", 4) == {"type": WEB_FETCH_DYNAMIC, "name": "web_fetch", "max_uses": 4}
    assert web_fetch_tool("claude-sonnet-5-5", 4)["type"] == WEB_FETCH_DYNAMIC
    assert web_fetch_tool("claude-haiku-5-5", 4)["type"] == WEB_FETCH_BASIC


async def test_the_scout_loads_a_page_and_says_when_one_fails(seeded: Config) -> None:
    fetched = message(
        [
            {"type": "server_tool_use", "id": "f1", "name": "web_fetch", "input": {"url": "https://example.com"}},
            {"type": "web_fetch_tool_result", "tool_use_id": "f1", "content": {"type": "web_fetch_result", "url": "https://example.com", "content": {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "Example Domain"}}}},
            {"type": "server_tool_use", "id": "f2", "name": "web_fetch", "input": {"url": "https://example.org/missing"}},
            {"type": "web_fetch_tool_result", "tool_use_id": "f2", "content": {"type": "web_fetch_tool_result_error", "error_code": "url_not_accessible"}},
            {"type": "text", "text": "It is the IANA example page."},
        ],
        server_tool_use={"web_search_requests": 0, "web_fetch_requests": 2},
    )
    client = Client([fetched])
    w = World(seeded, client)
    job = await w.run("Rook", "Take a look at https://example.com and say what it is.")
    request = client.requests[0]
    assert request["tools"][-1] == {"type": WEB_FETCH_BASIC, "name": "web_fetch", "max_uses": 5}
    assert "load the page yourself with web_fetch" in request["system"][0]["text"]
    steps = [s.text for s in job.steps]
    assert "Fetched a page: https://example.com" in steps
    assert "Could not load https://example.org/missing (url_not_accessible)" in steps
    audits = [(a.tool, a.result) for a in w.memory.audits if a.tool == "web_fetch" and a.result != "allowed"]
    assert ("web_fetch", "failed: url_not_accessible") in audits
    assert job.status == "done"


async def test_web_fetch_follows_its_tier(seeded: Config) -> None:
    seeded.gate.tiers["web_fetch"] = "never"
    client = Client([text("I could not load it.")])
    w = World(seeded, client)
    await w.run("Rook", "Look at https://example.com.")
    assert "web_fetch" not in offered(client.requests[0]) and "web_search" in offered(client.requests[0])
    assert "web_fetch" not in client.requests[0]["system"][0]["text"].split("Your tools for this job:")[1]


async def test_the_host_is_told_to_hand_web_work_to_the_scout(daemon: Daemon) -> None:
    spec = next(s for s in daemon.components.tools.specs() if s.name == "hand_off")
    assert spec.description == HAND_OFF
    for words in (
        "the scout for anything that needs the web",
        "hand it off at once and tell the owner it is under way: do not ask whether to",
        "open_url only opens a page on the Mac's screen",
    ):
        assert words in spec.description
    summary = daemon.awareness.summary()
    assert "hand it to the scout at once" in summary and "Do not ask whether to" in summary
    persona = (daemon.config.paths.house / "agents" / "host.md").read_text()
    assert "you hand it off" in persona and "goes to the scout" in persona
