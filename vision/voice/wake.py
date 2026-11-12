"""Is an utterance addressed to the assistant? And is it a stop, or our own echo?

All matching works on the transcript only, so it is pure and fast:

- `WakeMatcher.strip(text)` finds a leading "hey <name>" or "<name>",
  tolerant of punctuation and small recognition errors ("fission" for
  "vision"), and returns the rest of the text.
- `StopMatcher.matches(text)` recognises the short stop phrases.
- `residual(text, spoken)` drops the words that repeat what the assistant was
  saying, so it never hears itself.
- `Addressing` combines the wake phrase, push to talk and the follow-up
  window into one decision.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_WORD_SPAN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")
_LEAD_JUNK = re.compile(r"^[\s,.;:!?…\-–—]+")

GREETINGS = frozenset({"hey", "hi", "hay", "hello", "ok", "okay", "a", "yo"})
FILLERS = frozenset({"um", "uh", "er", "erm", "so", "oh", "well", "please", "now", "just"})


def words(text: str) -> list[str]:
    """Lower-case words without punctuation."""
    return _WORD.findall(text.lower().replace("’", "'"))


def _bare(word: str) -> str:
    for suffix in ("'s", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)]
    return word


def sounds_like(heard: str, target: str) -> bool:
    """True when `heard` is `target` up to a small recognition error.

    Short targets (three letters or fewer) must match exactly; longer ones
    may differ by about a quarter of their letters but not in length by more
    than one, so "fission" passes for "vision" and "television" does not.
    """
    heard, target = _bare(heard), _bare(target)
    if heard == target:
        return True
    if len(target) <= 3 or abs(len(heard) - len(target)) > 1:
        return False
    return SequenceMatcher(None, heard, target, autojunk=False).ratio() >= 0.75


class WakeMatcher:
    """Finds the wake phrase, built from the assistant's name, at the start of a transcript."""

    def __init__(self, name: str) -> None:
        self.name_words = words(name)
        if not self.name_words:
            raise ValueError(f"the assistant's name {name!r} has no letters to listen for")
        self._joined = "".join(self.name_words)

    def name_at(self, ws: list[str], i: int) -> int:
        """How many words starting at `ws[i]` spell the name (0 if they do not)."""
        n = len(self.name_words)
        for size in sorted({n, max(1, n - 1), n + 1}):
            chunk = ws[i : i + size]
            if len(chunk) == size and sounds_like("".join(chunk), self._joined):
                return size
        return 0

    def strip(self, text: str) -> str | None:
        """The text after a leading wake phrase, or None when there is none.

        An empty string means the wake phrase was said on its own.
        """
        spans = list(_WORD_SPAN.finditer(text))
        ws = [m.group().lower().replace("’", "'") for m in spans]
        i = 0
        while i < len(ws) and ws[i] in FILLERS:
            i += 1
        if i < len(ws) and ws[i] in GREETINGS and self.name_at(ws, i + 1):
            i += 1
        size = self.name_at(ws, i) if i < len(ws) else 0
        if not size:
            return None
        rest = _LEAD_JUNK.sub("", text[spans[i + size - 1].end() :]).strip()
        return rest[:1].upper() + rest[1:]


class StopMatcher:
    """Recognises "stop", "cancel" or "<name> stop", alone or with a filler."""

    def __init__(self, wake: WakeMatcher, phrases: Iterable[str]) -> None:
        self._wake = wake
        self._phrases = {tuple(c) for p in phrases if (c := self.core(words(p)))}

    def core(self, ws: list[str]) -> list[str]:
        """The words that carry the meaning: no name, greeting or filler."""
        out: list[str] = []
        i = 0
        while i < len(ws):
            size = self._wake.name_at(ws, i)
            if size:
                i += size
                continue
            if ws[i] not in FILLERS and ws[i] not in GREETINGS:
                out.append(ws[i])
            i += 1
        return out

    def matches(self, text: str | list[str]) -> bool:
        ws = words(text) if isinstance(text, str) else text
        core = self.core(ws)
        if not core or len(core) > 3:
            return False
        if tuple(core) in self._phrases:
            return True
        return all((w,) in self._phrases for w in core)


def residual(text: str, spoken: Iterable[str]) -> list[str]:
    """The words of `text` that do not repeat the assistant's own `spoken` words.

    Only runs of two or more words count as a repeat, so a lone "stop" from
    the user still gets through when the assistant happened to say "stop".
    """
    heard = words(text)
    said = [w for sentence in spoken for w in words(sentence)]
    if not said:
        return heard
    matched: set[int] = set()
    for block in SequenceMatcher(None, heard, said, autojunk=False).get_matching_blocks():
        if block.size >= 2:
            matched.update(range(block.a, block.a + block.size))
    return [w for i, w in enumerate(heard) if i not in matched]


@dataclass(slots=True)
class Addressing:
    """Decides whether an utterance is for the assistant.

    It is when push to talk was held at any time during the utterance, when it
    starts with the wake phrase, or when it started inside the open window:
    the follow-up window after a reply, or a moment after the wake phrase was
    said on its own. Times are `time.monotonic()` seconds.
    """

    wake: WakeMatcher
    window_s: float
    ptt_down: bool = False
    ptt_released_at: float = float("-inf")
    window_until: float = float("-inf")

    def ptt(self, down: bool, now: float) -> None:
        if self.ptt_down and not down:
            self.ptt_released_at = now
        self.ptt_down = down

    def open_window(self, now: float) -> None:
        self.window_until = now + self.window_s

    def held_during(self, started_at: float) -> bool:
        return self.ptt_down or self.ptt_released_at >= started_at

    def decide(self, text: str, started_at: float, now: float) -> str | None:
        """The text to pass on, or None to drop the utterance."""
        text = text.strip()
        if not words(text):
            return None
        stripped = self.wake.strip(text)
        if stripped == "":
            self.open_window(now)
            return None
        if stripped is not None:
            return stripped
        if self.held_during(started_at) or started_at <= self.window_until:
            return text
        return None
