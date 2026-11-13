"""The one error a local backend raises: a `BrainError` for the user, carried as an exception."""

from __future__ import annotations

from vision.core.interfaces import BrainError


class LocalModelError(Exception):
    def __init__(self, error: BrainError) -> None:
        super().__init__(error.message)
        self.error = error
