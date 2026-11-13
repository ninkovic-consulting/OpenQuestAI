"""Wake phrase, stop phrases, echo guard and the addressing decision (no models)."""

from __future__ import annotations

import pytest

from vision.voice.wake import (
    ALWAYS_MIN_VOICED_S,
    ALWAYS_MIN_WORDS,
    Addressing,
    StopMatcher,
    WakeMatcher,
    enough_for_always,
    residual,
    sounds_like,
)


@pytest.fixture
def wake() -> WakeMatcher:
    return WakeMatcher("Vision")


@pytest.mark.parametrize(
    ("heard", "rest"),
    [
        ("Hey Vision, what time is it?", "What time is it?"),
        ("hey vision what time is it", "What time is it"),
        ("Vision, turn on the lights.", "Turn on the lights."),
        ("Vision. Turn on the lights.", "Turn on the lights."),
        ("Hey, Vision! Are you there?", "Are you there?"),
        ("Hi Vision, hello.", "Hello."),
        ("Okay vision, play music", "Play music"),
        ("A vision, what's new?", "What's new?"),
        ("Um, hey Vision, what's new?", "What's new?"),
        ("Hey Fission, what time is it?", "What time is it?"),
        ("Visions, what time is it?", "What time is it?"),
        ("Vision's on? What time is it?", "On? What time is it?"),
        ("Hey Vi sion, what time is it?", "What time is it?"),
        ("Hey Vision.", ""),
        ("Vision", ""),
    ],
)
def test_wake_phrase_is_found_and_stripped(wake: WakeMatcher, heard: str, rest: str) -> None:
    assert wake.strip(heard) == rest


@pytest.mark.parametrize(
    "heard",
    [
        "What time is it?",
        "My vision is blurry today.",
        "Television is on.",
        "Revision of the plan is due.",
        "Hey, what time is it?",
        "Decision made, let's go.",
        "",
        "...",
    ],
)
def test_near_misses_are_not_wake_phrases(wake: WakeMatcher, heard: str) -> None:
    assert wake.strip(heard) is None


def test_wake_phrase_follows_the_configured_name() -> None:
    atlas = WakeMatcher("Atlas")
    assert atlas.strip("Hey Atlas, what's up?") == "What's up?"
    assert atlas.strip("Hey Vision, what's up?") is None
    two = WakeMatcher("Mister Robot")
    assert two.strip("Hey Mister Robot, status?") == "Status?"
    assert two.strip("Mister Robot status") == "Status"


def test_short_names_must_match_exactly() -> None:
    al = WakeMatcher("Al")
    assert al.strip("Al, lights off") == "Lights off"
    assert al.strip("All lights off") is None
    assert not sounds_like("ale", "al")


def test_name_without_letters_is_refused() -> None:
    with pytest.raises(ValueError):
        WakeMatcher("!!!")


@pytest.fixture
def stops(wake: WakeMatcher) -> StopMatcher:
    return StopMatcher(wake, ["vision stop", "stop", "cancel"])


@pytest.mark.parametrize(
    "heard",
    ["Stop.", "stop", "Cancel!", "Vision, stop.", "Vision stop", "Hey Vision, stop!",
     "Stop, stop.", "Please stop.", "Okay, cancel.", "Fission, stop."],
)
def test_stop_phrases(stops: StopMatcher, heard: str) -> None:
    assert stops.matches(heard)


@pytest.mark.parametrize(
    "heard",
    ["Don't stop the music.", "Stop the timer at five.", "Vision", "", "Cancel my meeting tomorrow",
     "bus stop", "unstoppable"],
)
def test_not_stop_phrases(stops: StopMatcher, heard: str) -> None:
    assert not stops.matches(heard)


def test_stop_phrase_with_another_name() -> None:
    atlas = WakeMatcher("Atlas")
    assert StopMatcher(atlas, ["stop", "Atlas stop"]).matches("Atlas, stop!")


def test_residual_removes_what_the_assistant_is_saying() -> None:
    spoken = ["The front door is locked.", "Do not stop the music."]
    assert residual("the front door is locked", spoken) == []
    assert residual("Front door is locked, stop!", spoken) == ["stop"]
    assert residual("do not stop the music", spoken) == []
    assert residual("Stop.", []) == ["stop"]
    assert residual("Vision, stop.", spoken) == ["vision", "stop"]
    assert residual("the music is locked", spoken) == ["is", "locked"]


def test_addressing_by_wake_phrase(wake: WakeMatcher) -> None:
    a = Addressing(wake, window_s=20)
    assert a.decide("Hey Vision, lights on.", started_at=0, now=1) == "Lights on."
    assert a.decide("Lights on.", started_at=0, now=1) is None
    assert a.decide("", started_at=0, now=1) is None


def test_follow_up_window(wake: WakeMatcher) -> None:
    a = Addressing(wake, window_s=20)
    a.open_window(100.0)
    assert a.decide("And tomorrow?", started_at=110, now=112) == "And tomorrow?"
    assert a.decide("And tomorrow?", started_at=120, now=121) == "And tomorrow?"
    assert a.decide("And tomorrow?", started_at=120.5, now=121) is None
    assert a.decide("Vision, and tomorrow?", started_at=110, now=112) == "And tomorrow?"


def test_wake_phrase_alone_opens_the_window(wake: WakeMatcher) -> None:
    a = Addressing(wake, window_s=20)
    assert a.decide("Hey Vision.", started_at=0, now=1) is None
    assert a.decide("What's the weather?", started_at=3, now=5) == "What's the weather?"
    assert a.decide("What's the weather?", started_at=30, now=31) is None


def test_push_to_talk(wake: WakeMatcher) -> None:
    a = Addressing(wake, window_s=20)
    a.ptt(True, now=10)
    assert a.decide("Lights on.", started_at=11, now=12) == "Lights on."
    a.ptt(False, now=13)
    assert a.decide("Lights off.", started_at=12.5, now=14) == "Lights off."  # held during it
    assert a.decide("Lights off.", started_at=13.5, now=15) is None
    a.ptt(True, now=20)
    assert a.decide("Hey Vision, lights off.", started_at=19, now=21) == "Lights off."


# ---------------------------------------------------------------- listening modes


def test_the_name_alone_or_after_hey_wakes_it() -> None:
    a = Addressing(WakeMatcher("Vision"), window_s=20)
    assert a.decide("Vision, what's the time?", started_at=0, now=1) == "What's the time?"
    assert a.decide("Hey Vision, what's the time?", started_at=0, now=1) == "What's the time?"
    assert a.decide("Vision what's the time", started_at=0, now=1) == "What's the time"


def test_another_name_is_the_one_listened_for() -> None:
    a = Addressing(WakeMatcher("Ada Lovelace"), window_s=20)
    assert a.decide("Ada Lovelace, what's the time?", started_at=0, now=1) == "What's the time?"
    assert a.decide("Hey Ada Lovelace, what's the time?", started_at=0, now=1) == "What's the time?"
    assert a.decide("Vision, what's the time?", started_at=0, now=1) is None


def test_hold_takes_only_what_is_said_while_holding() -> None:
    a = Addressing(WakeMatcher("Vision"), window_s=20, mode="hold")
    assert a.decide("Vision, lights on.", started_at=0, now=1) is None
    a.open_window(1)
    assert a.decide("And tomorrow?", started_at=2, now=3) is None  # no follow-up window in hold
    a.ptt(True, 5)
    assert a.decide("Vision, lights on.", started_at=5, now=6) == "Lights on."
    a.ptt(False, 7)
    assert a.decide("Lights off.", started_at=6.5, now=8) == "Lights off."  # the tail of the hold


def test_always_takes_what_clears_the_floor_without_the_name() -> None:
    a = Addressing(WakeMatcher("Vision"), window_s=20, mode="always")
    assert a.decide("What is on my calendar today?", started_at=0, now=2, voiced_s=1.4) == "What is on my calendar today?"
    assert a.decide("Okay thanks.", started_at=0, now=2, voiced_s=0.9) is None  # two words
    assert a.decide("(coughs) (coughs) (coughs)", started_at=0, now=2, voiced_s=0.9) is None
    assert a.decide("[keyboard clicking sounds]", started_at=0, now=2, voiced_s=0.9) is None
    assert a.decide("Um what now", started_at=0, now=2, voiced_s=0.3) is None  # too little speech
    assert a.decide("Vision, stop.", started_at=0, now=2, voiced_s=0.3) == "Stop."  # the name always counts


def test_always_takes_a_short_answer_in_the_follow_up_window() -> None:
    a = Addressing(WakeMatcher("Vision"), window_s=20, mode="always")
    a.open_window(10)
    assert a.decide("Yes please.", started_at=12, now=13, voiced_s=0.5) == "Yes please."
    assert a.decide("Yes please.", started_at=40, now=41, voiced_s=0.5) is None


def test_the_floor() -> None:
    assert enough_for_always("Turn the lights on", ALWAYS_MIN_VOICED_S)
    assert not enough_for_always("Turn the lights on", ALWAYS_MIN_VOICED_S - 0.01)
    assert not enough_for_always("Lights on", 2.0)
    assert not enough_for_always("*typing* *typing* *typing*", 2.0)
    assert ALWAYS_MIN_WORDS == 3
