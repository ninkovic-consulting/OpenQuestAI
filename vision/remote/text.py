"""Splitting a long reply into messages, at the most natural place that fits.

`measure` is the length a piece takes once the transport has escaped it, so
an escape never pushes a message over the limit and a split never falls
between an escape and the character it protects (the split is made in the
plain text, before escaping).
"""

from __future__ import annotations

import re
from collections.abc import Callable

Measure = Callable[[str], int]

_BREAKS = (re.compile(r"\n\s*\n"), re.compile(r"\n"), re.compile(r"[.!?;:]\s"), re.compile(r"[,)]\s"), re.compile(r"\s"))


def split_text(text: str, limit: int, measure: Measure = len) -> list[str]:
    """Pieces of `text`, each measuring at most `limit`, cut at paragraph, line,
    sentence, clause or word ends when one falls in the second half of a piece."""
    if limit < 1:
        raise ValueError("limit must be positive")
    pieces: list[str] = []
    rest = text.strip()
    while rest:
        if measure(rest) <= limit:
            pieces.append(rest)
            break
        fit = _longest_fit(rest, limit, measure)
        cut = _natural_cut(rest[:fit]) or fit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return [p for p in pieces if p]


def _longest_fit(text: str, limit: int, measure: Measure) -> int:
    """The longest prefix length that measures within `limit` (at least 1)."""
    low, high = 1, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if measure(text[:mid]) <= limit:
            low = mid
        else:
            high = mid - 1
    return low


def _natural_cut(window: str) -> int | None:
    """Where to cut `window`: just after the last natural break in its second half."""
    half = len(window) // 2
    for pattern in _BREAKS:
        ends = [m.end() for m in pattern.finditer(window) if m.end() > half]
        if ends:
            return ends[-1]
    return None


def clip(text: str, limit: int) -> str:
    """At most `limit` characters, with an ellipsis when cut."""
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"
