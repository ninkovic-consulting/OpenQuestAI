"""The text the brain is given: the local time only when the words need it, never in the system prompt."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vision.core.localtime import now_words
from vision.core.turns import TurnOrigin, brain_text, mentions_time

NOW = datetime(2026, 11, 12, 14, 3, tzinfo=ZoneInfo("Europe/Berlin"))


def test_now_in_words() -> None:
    assert now_words(NOW) == "Thursday 12 November 2026, 14:03 (Europe/Berlin)"


@pytest.mark.parametrize(
    "text",
    ["in one minute, remind me to stretch", "every weekday at nine", "in twenty minutes", "What time is it?", "at 7:30 tomorrow"],
)
def test_words_about_time_get_the_time(text: str) -> None:
    assert mentions_time(text)
    assert brain_text(text, TurnOrigin("voice"), NOW) == f"{text}\n\n[Local time now: {now_words(NOW)}.]"


@pytest.mark.parametrize("text", ["Hello there", "Please think this through for me", "Open Safari"])
def test_other_words_go_as_they_are(text: str) -> None:
    assert brain_text(text, TurnOrigin("text"), NOW) == text


def test_an_automation_says_what_it_is() -> None:
    origin = TurnOrigin("automation", "a1", "Stretch")
    got = brain_text("Remind the user to stretch.", origin, NOW)
    assert got.startswith('[Automation "Stretch" is due now, Thursday 12 November 2026, 14:03 (Europe/Berlin).')
    assert got.endswith("]\nRemind the user to stretch.")
