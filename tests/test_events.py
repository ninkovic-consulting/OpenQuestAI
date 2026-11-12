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
    "user.utterance": {"text": "What time is it?", "source": "voice"},
    "vision.delta": {"text": "It is"},
    "vision.reply": {"text": "It is noon.", "turn_id": "abc123"},
    "voice.level": {"level": 0.42},
    "room.state": {"room": "hall", "state": "active"},
    "gate.request": {
        "id": "g1",
        "tool": "shell",
        "summary": "Run ls",
        "detail": "ls -la",
        "expires_at": 1731400060.0,
    },
    "gate.resolved": {"id": "g1", "decision": "timeout"},
    "brain.fallback": {"from": "claude", "to": "local", "reason": "offline"},
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
    "notice": {"level": "warn", "text": "Voice is off."},
    "hello": {"token": "t0k"},
    "input.text": {"text": "hello"},
    "input.ptt": {"down": True},
    "input.interrupt": {},
    "gate.decision": {"id": "g1", "decision": "allow"},
}


def test_every_type_has_a_sample() -> None:
    assert set(SAMPLES) == set(EVENT_TYPES)
    assert OUTBOUND_TYPES | INBOUND_TYPES == set(EVENT_TYPES)
    assert not OUTBOUND_TYPES & INBOUND_TYPES
    assert INBOUND_TYPES == {"hello", "input.text", "input.ptt", "input.interrupt", "gate.decision"}


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
