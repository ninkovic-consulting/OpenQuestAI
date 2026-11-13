"""The owner's profile: checking, partial updates, the file a person edits, and the words."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from vision.memory import profile
from vision.memory.profile import BadProfile, Profile


@pytest.mark.parametrize(
    ("part", "value", "said"),
    [
        ("name", "De\x07ni", "one line of plain text"),
        ("name", "Sam\nSa", "one line of plain text"),
        ("name", "x" * 61, "at most 60 characters"),
        ("business", "y" * 601, "at most 600 characters"),
        ("notes", "z" * 2001, "at most 2000 characters"),
        ("notes", "ok\x00", "without control characters"),
        ("notes", "First\n## Call me\nBob", "start with ##"),
        ("name", 42, "Send text"),
        ("age", "40", "no part called 'age'"),
    ],
)
def test_bad_values_are_refused_plainly(part: str, value: object, said: str) -> None:
    with pytest.raises(BadProfile, match=said):
        profile.clean(part, value)


def test_values_are_tidied() -> None:
    assert profile.clean("name", "  Sam  ") == "Sam"
    assert profile.clean("notes", "Line one\r\n\tLine two") == "Line one\n\tLine two"
    assert profile.clean("business", "") == ""


def test_only_the_parts_given_change(tmp_path: Path) -> None:
    profile.update(tmp_path, {"name": "Sam", "business": "A bakery in Graz."})
    after = profile.update(tmp_path, {"notes": "Invoices go out on Fridays."})
    assert after == Profile("Sam", "A bakery in Graz.", "Invoices go out on Fridays.")
    assert profile.update(tmp_path, {"business": ""}) == Profile("Sam", "", "Invoices go out on Fridays.")
    assert profile.read(tmp_path) == Profile("Sam", "", "Invoices go out on Fridays.")


def test_a_refused_part_changes_nothing(tmp_path: Path) -> None:
    profile.update(tmp_path, {"name": "Sam"})
    with pytest.raises(BadProfile):
        profile.update(tmp_path, {"business": "Fine", "name": "x" * 99})
    assert profile.read(tmp_path) == Profile("Sam")


def test_the_file_is_plain_markdown_and_private(tmp_path: Path) -> None:
    profile.update(tmp_path, {"name": "Sam", "notes": "Two lines\nof notes."})
    path = tmp_path / "owner.md"
    body = path.read_text()
    assert body.startswith("# About the owner")
    assert "## Call me\n\nSam\n" in body and "## Keep in mind\n\nTwo lines\nof notes.\n" in body
    assert "## Business\n" in body
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_hand_edit_is_read_and_clipped_never_refused(tmp_path: Path) -> None:
    (tmp_path / "owner.md").write_text(
        "Some words of my own.\n\n## call ME\n\n  Sam\n  N.\n\n## Unknown part\n\nignored\n\n"
        "## Business\n\n" + "b" * 700 + "\n"
    )
    got = profile.read(tmp_path)
    assert got.name == "Sam N."
    assert got.business == "b" * 600
    assert got.notes == ""


def test_no_file_is_an_empty_profile(tmp_path: Path) -> None:
    assert profile.read(tmp_path) == Profile()
    assert profile.read(tmp_path).empty


def test_prompt_words() -> None:
    full = profile.prompt_text(Profile("Sam", "Northfield Studio: software for small firms.", "Answer in English."), may_update=True)
    assert full.startswith("# The owner\n\nThe owner asks to be called Sam. Address them by that name.")
    assert "in the owner's words: Northfield Studio: software for small firms." in full
    assert "always keep this in mind:\nAnswer in English." in full
    assert "update_profile" in full
    resident = profile.prompt_text(Profile("Sam"), may_update=False)
    assert "update_profile" not in resident and "business" not in resident
    empty = profile.prompt_text(Profile(), may_update=True)
    assert "has not said yet" in empty and "update_profile" in empty


def test_owner_in_a_few_words() -> None:
    assert profile.owner_words(Profile("Sam", "A bakery.\nSecond line.")) == "Sam; their business: A bakery."
    assert profile.owner_words(Profile("Sam")) == "Sam; no business given"
    assert profile.owner_words(Profile(business="b" * 100)).endswith("…")
    assert profile.owner_words(Profile()).startswith("not told yet")
