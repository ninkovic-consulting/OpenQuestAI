"""Messages that wait for the assistant to be free, and the one list every window shows.

Two lanes wait apart and never mix their words into one turn: the window's
(typed while a turn ran; `session.py` keeps it) and the phone's (sent while
the assistant was busy; `vision.remote.channel` keeps it). Each lane tells the
`WaitingBoard` what it holds whenever that changes; the board publishes the
whole list as `queue.changed`, window's lane first because it goes first, and
answers `/api/state` with the same list, so a window that reloads or opens
later shows what waits.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from vision.core.bus import Bus
from vision.core.events import QueueChanged, WaitingMessage, WaitingSource
from vision.core.interfaces import Picture
from vision.core.turns import image_only

PREVIEW_CHARS = 140
"""The start of a waiting message that windows show; the rest goes with the turn."""


def new_id() -> str:
    return uuid.uuid4().hex


def preview(text: str, images: int = 0) -> str:
    """The start of the words on one line, or what the images are when there are none."""
    flat = " ".join(text.split())
    if not flat:
        return image_only(images)
    return flat if len(flat) <= PREVIEW_CHARS else flat[: PREVIEW_CHARS - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class Waiting:
    """One message that waits: its words and loaded images, where it came from and when."""

    text: str
    pictures: tuple[Picture, ...] = ()
    source: WaitingSource = "text"
    id: str = field(default_factory=new_id)
    at: float = field(default_factory=time.time)

    def view(self) -> WaitingMessage:
        return WaitingMessage(
            id=self.id,
            preview=preview(self.text, len(self.pictures)),
            images=len(self.pictures),
            source=self.source,
            at=self.at,
        )


def joined(batch: Sequence[Waiting]) -> str:
    """The words of several messages as one turn's text: one paragraph each, in order."""
    return "\n\n".join(m.text for m in batch if m.text)


class WaitingBoard:
    """What waits, in both lanes, published on every change."""

    def __init__(self, bus: Bus) -> None:
        self._bus = bus
        self._lanes: dict[WaitingSource, tuple[WaitingMessage, ...]] = {"text": (), "phone": ()}

    def show(self, lane: WaitingSource, items: Sequence[Waiting]) -> None:
        """This lane now holds `items`, in the order they will go."""
        views = tuple(m.view() for m in items)
        if views == self._lanes[lane]:
            return
        self._lanes[lane] = views
        self._bus.publish(QueueChanged(items=self.items()))

    def items(self) -> list[WaitingMessage]:
        return [*self._lanes["text"], *self._lanes["phone"]]

    def view(self) -> list[dict[str, object]]:
        """The list in the shape of `queue.changed`'s `items`, for `/api/state`."""
        return [m.model_dump(mode="json") for m in self.items()]
