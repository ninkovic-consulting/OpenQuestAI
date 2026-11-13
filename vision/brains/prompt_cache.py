"""The processed prompts kept between generations on the in-process model, so a turn reads only
what is new.

A model reads its whole prompt before the first word; the state that leaves
behind (mlx-lm's prompt cache, one key-value cache per layer) is what the next
token needs. Kept after a generation, it lets the next generation skip every
token it has in common with the one before: the system text, the tool list and
the earlier turns. Only the rest is read.

Entries are keyed by the exact token ids they were built from, and one is used
only for the tokens its key shares with the new prompt, from the first token
on: the state of a token prefix depends on those tokens alone, so whatever
changed in the beginning (the memory core, the tool list, the rule line, a
history cut short, another agent's job) simply ends the shared part there and
the cache is trimmed back to it. No text can carry over from one conversation
to another, because nothing is reused past the first token that differs.

An entry is taken out while a generation uses it (never copied, so it costs no
second copy of memory) and put back with the new tokens. Entries sharing fewer
than `MIN_SHARED` tokens with a prompt are left alone, so a resident's job
never takes the host's entry for the few template tokens every prompt starts
with. At most `MAX_ENTRIES` entries and `MAX_BYTES` are kept; past either, the
residents' jobs' entries go first, oldest first, then the host's: the owner
waits on the host, nobody waits on a job's next step.

Everything here runs on the backend's one MLX thread.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from vision.brains.local_chat import Who

log = logging.getLogger(__name__)

MAX_ENTRIES = 4
"""The host's conversation and a few jobs' at once."""
MAX_BYTES = 2 * 1024**3
"""The memory the kept prompts may hold between generations (the 4B model holds about
150 KB per token, so 2 GB is some 14,000 tokens)."""
MIN_SHARED = 64
"""Fewer shared tokens than this is the chat template's opening, not a shared prompt."""


class KV(Protocol):
    """A model's processed-prompt state, changed in place as tokens are read."""

    def trimmable(self) -> bool:
        """Whether tokens can be taken off the end (layers like linear attention cannot)."""
        ...

    def trim(self, n: int) -> None: ...

    def nbytes(self) -> int: ...

    def size(self) -> int | None:
        """The tokens it holds, when the cache can tell."""
        ...


@dataclass(slots=True)
class _Entry:
    tokens: list[int]
    kv: KV
    who: Who
    nbytes: int
    used: int


class PromptCaches:
    def __init__(self, *, max_entries: int = MAX_ENTRIES, max_bytes: int = MAX_BYTES) -> None:
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: list[_Entry] = []
        self._clock = 0

    @property
    def nbytes(self) -> int:
        return sum(e.nbytes for e in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def take(self, prompt: list[int], fresh: Callable[[], KV]) -> tuple[KV, int]:
        """A cache for `prompt` and how many of its first tokens it already holds (always fewer
        than all of them, since the last one is read to give the first word)."""
        best: _Entry | None = None
        shared = 0
        for entry in self._entries:
            n = _shared(entry.tokens, prompt)
            if n > shared:
                best, shared = entry, n
        shared = min(shared, len(prompt) - 1)
        if best is None or shared < MIN_SHARED:
            return fresh(), 0
        self._entries.remove(best)
        extra = len(best.tokens) - shared
        if extra and not best.kv.trimmable():
            return fresh(), 0  # it cannot be cut back to the shared part: dropped
        if extra:
            best.kv.trim(extra)
        return best.kv, shared

    def keep(self, tokens: list[int], kv: KV, who: Who) -> None:
        """Keep `kv`, which holds exactly `tokens`, then evict down to the bounds."""
        size = kv.size()
        if size is not None and size != len(tokens):
            log.warning("a prompt cache holds %d tokens, not %d; dropped", size, len(tokens))
            return
        self._clock += 1
        self._entries.append(_Entry(tokens, kv, who, kv.nbytes(), self._clock))
        while self._entries and (len(self._entries) > self._max_entries or self.nbytes > self._max_bytes):
            self._entries.remove(min(self._entries, key=lambda e: (e.who == "host", e.used)))


def _shared(a: list[int], b: list[int]) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n
