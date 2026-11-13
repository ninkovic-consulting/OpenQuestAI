import json
from typing import Any

import pytest

from vision.core.events import (
    EVENT_TYPES,
    INBOUND_TYPES,
    OUTBOUND_TYPES,
    BrainFallback,
    EventError,
    StateChanged,
    parse_event,
)

SAMPLES: dict[str, dict[str, Any]] = {
    "state.changed": {"state": "thinking", "brain": "claude"},
    "budget": {"month": "2026-11", "spent_usd": 1.25, "cap_usd": 150.0},
    "user.utterance": {"text": "What time is it?", "source": "voice", "images": [], "ids": []},
    "vision.delta": {"text": "It is"},
    "vision.reply": {"text": "It is noon.", "turn_id": "abc123", "status": "interrupted"},
    "voice.level": {"level": 0.42},
    "voice.listen": {"mode": "hold", "mic": "opening", "voice": True, "listening": "always", "shell_free": False},
    "room.state": {"room": "hall", "state": "active"},
    "gate.request": {
        "id": "g1",
        "tool": "shell",
        "summary": "Run ls",
        "detail": "ls -la",
        "expires_at": 1731400060.0,
        "agent": "checker",
        "agent_name": "Tock",
        "job": "3f2a91c0",
    },
    "gate.resolved": {"id": "g1", "decision": "timeout"},
    "brain.fallback": {"from": "claude", "to": "local", "reason": "offline"},
    "brain.mode": {
        "offline": True,
        "answering": "local",
        "local_backend": "mlx",
        "local_model": "mlx-community/Qwen3-4B-Instruct-2507-4bit",
        "local_tools": True,
        "local_images": False,
        "local_state": "ready",
        "local_bytes": 2_263_000_000,
        "local_cache_bytes": 310_000_000,
        "local_reading": [1200, 3400],
        "local_problem": None,
    },
    "house.changed": {"revision": 3},
    "automation.changed": {
        "id": "a1b2c3d4",
        "change": "updated",
        "automation": {"id": "a1b2c3d4", "name": "Stretch"},
    },
    "automation.started": {"id": "a1b2c3d4", "name": "Stretch"},
    "automation.finished": {
        "id": "a1b2c3d4",
        "name": "Stretch",
        "status": "needed_approval",
        "reply": "Time to stretch.",
    },
    "job.changed": {
        "id": "3f2a91c0",
        "title": "Run the tests",
        "agent": "checker",
        "room": "spare-room",
        "status": "working",
        "asked_by": "host",
        "parent": None,
        "created_at": 1731400000.0,
        "started_at": 1731400001.0,
        "ended_at": None,
        "needed_approval": False,
        "model": "mlx-community/Qwen3-4B-Instruct-2507-4bit",
        "local": True,
        "last_step": {"ts": 1731400002.0, "kind": "tool", "text": "Run a program: pytest -q"},
    },
    "agent.state": {"agent": "checker", "state": "waiting", "job": "3f2a91c0"},
    "presence": {"away": True, "known": True, "reason": "locked", "since": 1731400000.0, "away_after_s": 300.0},
    "procedure.changed": {"owner": "maker", "name": "release-the-shop", "change": "saved"},
    "proposal.changed": {"id": "a1b2c3d4", "kind": "tool", "status": "waiting", "agent": "maker", "waiting": 1},
    "made_tool.changed": {"name": "count_lines", "change": "disabled", "enabled": False},
    "queue.changed": {
        "items": [
            {"id": "m1", "preview": "And the tests?", "images": 0, "source": "text", "at": 1731400010.0},
            {"id": "p1", "preview": "The phone's.", "images": 2, "source": "phone", "at": 1731400011.0},
        ]
    },
    "notice": {"level": "warn", "text": "Voice is off."},
    "hello": {"token": "t0k"},
    "input.text": {"text": "hello", "images": [], "now": True, "id": "m1"},
    "input.ptt": {"down": True},
    "input.interrupt": {},
    "input.take_back": {"id": "m1"},
    "input.send_now": {"id": "m1"},
    "gate.decision": {"id": "g1", "decision": "allow"},
}


def test_every_type_has_a_sample() -> None:
    assert set(SAMPLES) == set(EVENT_TYPES)
    assert OUTBOUND_TYPES | INBOUND_TYPES == set(EVENT_TYPES)
    assert not OUTBOUND_TYPES & INBOUND_TYPES
    assert INBOUND_TYPES == {
        "hello",
        "input.text",
        "input.ptt",
        "input.interrupt",
        "input.take_back",
        "input.send_now",
        "gate.decision",
    }


@pytest.mark.parametrize("type_", sorted(SAMPLES))
def test_round_trip(type_: str) -> None:
    raw = json.dumps({"type": type_, "ts": 1731400000.5, "data": SAMPLES[type_]})
    event = parse_event(raw)
    assert type(event) is EVENT_TYPES[type_]
    assert event.ts == 1731400000.5
    assert event.to_envelope() == {"type": type_, "ts": 1731400000.5, "data": SAMPLES[type_]}
    assert parse_event(event.to_json()) == event


def test_brain_fallback_uses_from_on_the_wire() -> None:
    event = BrainFallback(from_="claude", to="local", reason="rate limit")
    assert event.data() == {"from": "claude", "to": "local", "reason": "rate limit"}


def test_state_changed_brain_is_optional() -> None:
    assert StateChanged(state="listening").data() == {"state": "listening", "brain": None}


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps({"type": "nope", "ts": 0, "data": {}}),
        json.dumps({"type": "input.text", "data": {"text": "x"}}),  # no ts
        json.dumps({"type": "input.text", "ts": 0, "data": {"text": ""}}),
        json.dumps({"type": "input.text", "ts": 0, "data": {"text": "x", "extra": 1}}),
        json.dumps({"type": "voice.level", "ts": 0, "data": {"level": 1.5}}),
        json.dumps({"type": "state.changed", "ts": 0, "data": {"state": "dancing"}}),
        json.dumps({"type": "gate.decision", "ts": 0, "data": {"id": "g", "decision": "timeout"}}),
        json.dumps({"type": "budget", "ts": 0, "data": {"month": "Nov", "spent_usd": 0, "cap_usd": 1}}),
        json.dumps({"type": "input.text", "ts": 0, "data": {}, "more": 1}),
    ],
)
def test_invalid_messages_raise(raw: str) -> None:
    with pytest.raises(EventError):
        parse_event(raw)
