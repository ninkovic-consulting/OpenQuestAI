"""What the phone channel needs from the daemon, and the daemon's side of it.

`Host` keeps the channel independent of the composition root (tests hand it
a fake); `DaemonHost` is the real one over a running `Daemon`.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from vision.core.bus import Bus
from vision.core.events import GateRequest, State
from vision.core.interfaces import AuditRecord, Picture, TurnRecord
from vision.core.waiting import Waiting
from vision.house.tools import load_catalog
from vision.presence import Seen
from vision.proposals.model import TOOL_PREFIX

if TYPE_CHECKING:
    import numpy as np

    from vision.app import Daemon

PHONE_NEVER = frozenset({"shell"})
"""Tools that are approved only at the Mac, whatever the phone settings say."""
PHONE_OFF_BY_DEFAULT = frozenset({"run_program"})
"""Tools the phone does not approve until the owner adds them in Settings, Phone: a
resident's `run_program` runs code from the project."""
MADE_PREFIX = TOOL_PREFIX
"""The tools agents wrote (`vision.proposals`) run only after a yes at the Mac: the owner
approved the script there and reads each run's input and reach there."""


class TurnsBusy(RuntimeError):
    """Another turn is running; try again once the assistant is idle."""


@dataclass(frozen=True, slots=True)
class Status:
    name: str
    state: State
    brain: str
    month: str
    spent_usd: float
    cap_usd: float


class Host(Protocol):
    @property
    def bus(self) -> Bus: ...

    def busy(self) -> bool:
        """True while a turn runs, someone speaks at the Mac, or a gate request waits."""
        ...

    async def run_turn(
        self,
        text: str,
        *,
        speak: bool,
        images: Sequence[Picture] = (),
        waited: int = 0,
        ids: Sequence[str] = (),
    ) -> TurnRecord:
        """Run a phone turn now, with the images that came with it, and wait for it.
        `waited` counts the messages that waited and go in it together, `ids` names them.
        Raises `TurnsBusy`."""
        ...

    def show_waiting(self, items: Sequence[Waiting]) -> None:
        """The phone's messages that wait now, for every window's list (`queue.changed`)."""
        ...

    async def keep_image(self, data: bytes) -> Picture:
        """Check, clean and keep an image the owner sent, as the window's upload does.
        Raises `vision.attachments.ImageRefused` with a line for people."""
        ...

    async def interrupt(self) -> None: ...
    def status(self) -> Status: ...
    async def audit(self, entry: AuditRecord) -> None: ...
    def open_request(self, request_id: str) -> GateRequest | None:
        """The gate request still waiting under this id, or None."""
        ...

    def tools(self) -> list[tuple[str, str]]:
        """Every tool behind the gate, the residents' included, as `(id, title)`."""
        ...

    def local_voice(self) -> LocalSpeech | None:
        """The running voice's models, or None when voice is not running."""
        ...

    def presence(self) -> Seen:
        """Whether the owner is at the Mac, read now."""
        ...

    def away_after_s(self) -> float:
        """How long without input counts as away (`[presence] away_after_s`)."""
        ...

    async def set_away_after(self, seconds: float) -> None:
        """Write and apply a new away time, as Settings does."""
        ...


class LocalSpeech(Protocol):
    async def transcribe(self, audio: np.ndarray) -> str: ...
    async def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...


class DaemonHost:
    def __init__(self, daemon: Daemon) -> None:
        self._d = daemon

    @property
    def bus(self) -> Bus:
        return self._d.bus

    def busy(self) -> bool:
        return self._d.busy()

    async def run_turn(
        self,
        text: str,
        *,
        speak: bool,
        images: Sequence[Picture] = (),
        waited: int = 0,
        ids: Sequence[str] = (),
    ) -> TurnRecord:
        session = self._d.session
        if session is None or self.busy():
            raise TurnsBusy
        try:
            return await session.run_phone(text, speak=speak, images=images, waited=waited, ids=ids)
        except RuntimeError as exc:
            raise TurnsBusy from exc

    def show_waiting(self, items: Sequence[Waiting]) -> None:
        self._d.waiting.show("phone", items)

    async def keep_image(self, data: bytes) -> Picture:
        return await asyncio.to_thread(self._d.images.add, data)

    async def interrupt(self) -> None:
        if self._d.session is not None:
            await self._d.session.interrupt()

    def status(self) -> Status:
        c = self._d.components
        budget = dataclasses.asdict(c.budget.status())
        return Status(self._d.config.assistant.name, self._d.snapshot.state, c.brain.name, **budget)

    async def audit(self, entry: AuditRecord) -> None:
        await self._d.components.memory.audit(entry)

    def open_request(self, request_id: str) -> GateRequest | None:
        return self._d.snapshot.gate_pending.get(request_id)

    def tools(self) -> list[tuple[str, str]]:
        """The host's tools, then the residents' (their requests reach the phone too)."""
        catalog = load_catalog()
        names = [spec.name for spec in self._d.components.tools.specs()]
        names += [t.id for t in catalog.values() if t.resident and t.id not in names]
        return [(n, catalog[n].title if n in catalog else n.replace("_", " ")) for n in names]

    def presence(self) -> Seen:
        return self._d.presence.check()

    def away_after_s(self) -> float:
        return self._d.config.presence.away_after_s

    async def set_away_after(self, seconds: float) -> None:
        await self._d.app.state.settings.patch({"presence": {"away_after_s": seconds}})

    def local_voice(self) -> LocalSpeech | None:
        if not self._d.voice_running:
            return None
        try:
            from vision.voice.service import LocalVoice
        except ImportError:
            return None
        voice = self._d.components.voice
        return voice if isinstance(voice, LocalVoice) else None
