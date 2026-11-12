"""One real round trip to the Anthropic API. Opt-in: `VISION_LIVE=1`.

The key is found the normal way, through `vision.core.secrets`; point
`VISION_ENV_FILE` at a `.env` holding `ANTHROPIC_API_KEY` for the run. Run with
`-s` to see the measurements. It never prints the key.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

from vision.brains.budget import MonthlyBudget
from vision.brains.claude import ClaudeBrain
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import TextDelta, ToolSpec, TurnDone
from vision.testing.fakes import FakeMemory, FakeToolHost

# Read before the autouse fixture points VISION_ENV_FILE at a missing file.
LIVE_ENV_FILE = os.environ.get("VISION_ENV_FILE")

pytestmark = pytest.mark.skipif(os.environ.get("VISION_LIVE") != "1", reason="set VISION_LIVE=1")


async def timed_turn(brain: ClaudeBrain, text: str) -> tuple[str, float | None, TurnDone]:
    started = time.perf_counter()
    first: float | None = None
    parts: list[str] = []
    done: Any = None
    async for event in brain.send(text):
        if isinstance(event, TextDelta):
            first = first if first is not None else time.perf_counter() - started
            parts.append(event.text)
        else:
            done = event
    assert isinstance(done, TurnDone), done
    return "".join(parts), first, done


async def test_live_talk_turn_and_tool_turn(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    if LIVE_ENV_FILE:
        monkeypatch.setenv("VISION_ENV_FILE", LIVE_ENV_FILE)
    calls: list[dict[str, Any]] = []

    async def secret_word(args: dict[str, Any]) -> str:
        calls.append(args)
        return "The secret word is marigold."

    spec = ToolSpec(
        "secret_word",
        "Returns today's secret word. Call this whenever the user asks for the secret word.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    tools = FakeToolHost({"secret_word": (spec, secret_word)})
    budget = MonthlyBudget(config, Bus())
    memory = FakeMemory("You are a concise voice assistant. Answer in one short sentence.")
    brain = ClaudeBrain(config, tools, memory, budget)
    await brain.start()
    assert brain.has_key, "no API key found through vision.core.secrets"
    try:
        text, ttft, done = await timed_turn(brain, "Say hello in five words.")
        print(f"\n[talk] ttft={ttft:.2f}s in={done.input_tokens} out={done.output_tokens} "
              f"stop={done.stop_reason} model={done.model} text={text!r}")
        assert text and done.stop_reason == "end_turn"
        after_first = budget.status().spent_usd

        text, ttft, done = await timed_turn(brain, "What is the secret word?")
        ttft_text = f"{ttft:.2f}s" if ttft is not None else "none"
        print(f"[tool] ttft={ttft_text} in={done.input_tokens} out={done.output_tokens} "
              f"stop={done.stop_reason} text={text!r} tool_calls={len(calls)}")
        status = budget.status()
        print(f"[budget] first turn ${after_first:.6f}, total ${status.spent_usd:.6f} ({status.month})")
        assert calls and "marigold" in text.lower()
    finally:
        await brain.close()
