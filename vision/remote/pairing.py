"""The one-time pairing code: six digits, shown in Settings, good for ten minutes.

Only one code is live at a time, issuing a new one voids the old, and a code
is used up by a match or by five wrong tries, so it cannot be guessed. Only
text that looks like a code counts as a try; "hello" does not burn it.
"""

from __future__ import annotations

import hmac
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

CODE_LENGTH = 6
CODE_TTL_S = 600.0
MAX_TRIES = 5
_SHAPE = re.compile(r"^\d{6}$")

Check = Literal["paired", "wrong", "expired", "none"]


@dataclass(frozen=True, slots=True)
class Code:
    code: str
    expires_at: float


def normalize(text: str) -> str:
    """`"482 913"`, `"482-913"` and `"pair 482913"` all read as `"482913"`."""
    return re.sub(r"[\s-]", "", text.strip().lower().removeprefix("pair"))


def looks_like_code(text: str) -> bool:
    return _SHAPE.match(normalize(text)) is not None


class Pairing:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._code: Code | None = None
        self._tries = 0

    def issue(self) -> Code:
        code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
        self._code = Code(code, self._clock() + CODE_TTL_S)
        self._tries = 0
        return self._code

    def current(self) -> Code | None:
        """The live code, or None when there is none or it has expired."""
        if self._code is not None and self._clock() >= self._code.expires_at:
            self._code = None
        return self._code

    def clear(self) -> None:
        self._code = None

    def check(self, text: str) -> Check:
        """Try `text` against the live code. A match uses the code up."""
        had = self._code
        code = self.current()
        if code is None:
            return "expired" if had is not None else "none"
        if hmac.compare_digest(normalize(text).encode(), code.code.encode()):
            self._code = None
            return "paired"
        self._tries += 1
        if self._tries >= MAX_TRIES:
            self._code = None
        return "wrong"
