"""Fakes for the phone channel: a transport that records, a host, ears and tokens."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vision.core.bus import Bus
from vision.core.events import GateRequest
from vision.attachments.clean import clean
from vision.core.interfaces import AuditRecord, Picture, TurnRecord
from vision.presence import Seen
from vision.remote.channel import PhoneChannel
from vision.remote.host import Status, TurnsBusy
from vision.remote.link import Link
from vision.remote.pairing import Pairing
from vision.remote.store import PhoneState
from vision.remote.transport import Attachment, BotIdentity, Button, Handlers, Incoming, Press

OWNER = "111"
STRANGER = "222"
CHAT = "700"


@dataclass
class FakeTransport:
    sent: list[tuple[str, str]] = field(default_factory=list)
    buttons: list[tuple[str, str, list[Button]]] = field(default_factory=list)
    edits: list[tuple[str, str, str]] = field(default_factory=list)
    acks: list[tuple[str, str | None]] = field(default_factory=list)
    typing_in: list[str] = field(default_factory=list)
    voices: list[tuple[str, int, float]] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    ids: int = 0

    @property
    def max_text(self) -> int:
        return 2000

    def _id(self) -> str:
        self.ids += 1
        return f"m{self.ids}"

    async def identify(self) -> BotIdentity:
        return BotIdentity("900", "Vision Bot")

    async def listen(self, handlers: Handlers) -> None:
        handlers.online(True)
        await asyncio.Event().wait()

    async def send(self, chat_id: str, text: str) -> str:
        self.sent.append((chat_id, text))
        return self._id()

    async def send_buttons(self, chat_id: str, text: str, buttons: list[Button]) -> str:
        self.buttons.append((chat_id, text, buttons))
        return self._id()

    async def edit(self, chat_id: str, message_id: str, text: str) -> None:
        self.edits.append((chat_id, message_id, text))

    async def acknowledge(self, press: Press, text: str | None) -> None:
        self.acks.append((press.press_id, text))

    async def typing(self, chat_id: str) -> None:
        self.typing_in.append(chat_id)

    async def fetch(self, attachment: Attachment, limit: int) -> bytes:
        return self.files[attachment.url]

    async def send_voice(self, chat_id: str, ogg: bytes, duration_s: float, waveform: bytes) -> str:
        self.voices.append((chat_id, len(ogg), duration_s))
        return self._id()

    async def close(self) -> None:
        return None

    def texts(self) -> list[str]:
        return [text for _, text in self.sent]


@dataclass
class FakeHost:
    bus: Bus = field(default_factory=Bus)
    is_busy: bool = False
    turns: list[tuple[str, bool]] = field(default_factory=list)
    pictures: list[tuple[Picture, ...]] = field(default_factory=list)
    """The images that went with each turn, in step with `turns`."""
    kept: list[Picture] = field(default_factory=list)
    audits: list[AuditRecord] = field(default_factory=list)
    pending: dict[str, GateRequest] = field(default_factory=dict)
    tool_ids: tuple[str, ...] = ("remember", "recall", "open_app", "open_url", "shell", "delete_automation")
    turn_s: float = 0.0
    running: int = 0
    most_at_once: int = 0
    interrupts: int = 0
    seen: Seen = field(default_factory=lambda: Seen(False, True, None, 0.0, 1.0))
    away_after: float = 300.0
    _gate: asyncio.Event = field(default_factory=asyncio.Event)

    def leave(self, since: float, reason: str = "locked") -> None:
        """The owner left the Mac at `since`."""
        self.seen = Seen(True, True, reason, since, 600.0)  # type: ignore[arg-type]

    def come_back(self) -> None:
        self.seen = Seen(False, True, None, time.time(), 0.0)

    def presence(self) -> Seen:
        return self.seen

    def away_after_s(self) -> float:
        return self.away_after

    async def set_away_after(self, seconds: float) -> None:
        self.away_after = seconds

    def busy(self) -> bool:
        return self.is_busy or self.running > 0

    async def keep_image(self, data: bytes) -> Picture:
        """The real checks and cleaning (`clean`), without a store on disk."""
        cleaned = clean(data)
        picture = Picture(uuid.uuid4().hex, cleaned.media_type, cleaned.width, cleaned.height, cleaned.data)
        self.kept.append(picture)
        return picture

    async def run_turn(self, text: str, *, speak: bool, images: tuple[Picture, ...] = ()) -> TurnRecord:
        if self.busy():
            raise TurnsBusy
        self.running += 1
        self.most_at_once = max(self.most_at_once, self.running)
        started = time.time()
        status = "ok"
        try:
            self._gate.clear()
            try:
                await asyncio.wait_for(self._gate.wait(), self.turn_s)
                status = "interrupted"
            except TimeoutError:
                pass
            self.turns.append((text, speak))
            self.pictures.append(tuple(images))
        finally:
            self.running -= 1
        reply = f"Echo: {text}" if status == "ok" else "Echo"
        return TurnRecord("t", started, time.time(), "phone", text, reply, status, "fake", "fake-1")  # type: ignore[arg-type]

    async def interrupt(self) -> None:
        self.interrupts += 1
        self._gate.set()

    def status(self) -> Status:
        return Status("Vision", "idle", "fake", "2026-11", 1.25, 150.0)

    async def audit(self, entry: AuditRecord) -> None:
        self.audits.append(entry)

    def open_request(self, request_id: str) -> GateRequest | None:
        return self.pending.get(request_id)

    def tools(self) -> list[tuple[str, str]]:
        return [(t, t.title()) for t in self.tool_ids]

    def local_voice(self) -> None:
        return None


@dataclass
class FakeEars:
    have_models: bool = True
    words: str = "what is on today"
    fail: bool = False
    heard: list[int] = field(default_factory=list)
    closed: bool = False

    def installed(self) -> bool:
        return self.have_models

    async def transcribe(self, audio: np.ndarray) -> str:
        if self.fail:
            raise RuntimeError("model broke")
        self.heard.append(int(audio.size))
        return self.words

    async def speak(self, text: str) -> tuple[np.ndarray, int]:
        return np.full(24_000, 0.1, dtype=np.float32), 24_000

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeDecoder:
    name: str = "fake"
    present: bool = True

    def available(self) -> bool:
        return self.present

    def decode(self, data: bytes) -> np.ndarray:
        return np.zeros(16_000, dtype=np.float32)


@dataclass
class MemoryTokens:
    token: str | None = None
    puts: int = 0

    def get(self) -> str | None:
        return self.token

    def put(self, token: str) -> None:
        self.puts += 1
        self.token = token

    def delete(self) -> None:
        self.token = None


@dataclass
class Rig:
    """A channel over fakes: the state, its saves, and every fake to look at."""

    channel: PhoneChannel
    transport: FakeTransport
    host: FakeHost
    ears: FakeEars
    state: PhoneState
    pairing: Pairing
    saves: list[PhoneState]
    link: Link


def rig(
    *,
    paired: bool = True,
    ears: FakeEars | None = None,
    decoders: list[Any] | None = None,
    clock: list[float] | None = None,
) -> Rig:
    transport, host = FakeTransport(), FakeHost()
    the_ears = ears or FakeEars()
    state = PhoneState()
    if paired:
        state.owner_id, state.owner_name, state.chat_id, state.paired_at = OWNER, "Owner", CHAT, 1.0
    saves: list[PhoneState] = []

    async def save() -> None:
        saves.append(PhoneState(**{k: getattr(state, k) for k in state.__dataclass_fields__}))

    times = clock if clock is not None else [1000.0]
    pairing = Pairing(clock=lambda: times[0])
    link = Link(host, pairing, lambda: state, save, lambda: transport)  # type: ignore[arg-type]
    channel = PhoneChannel(link, the_ears, decoders if decoders is not None else [FakeDecoder()], clock=lambda: times[0])  # type: ignore[arg-type]
    return Rig(channel, transport, host, the_ears, state, pairing, saves, link)


def dm(text: str, user: str = OWNER, *, direct: bool = True, attachments: tuple[Attachment, ...] = ()) -> Incoming:
    return Incoming("m0", CHAT, user, "Owner" if user == OWNER else "Someone", direct, text, attachments)


def voice_note(url: str = "cdn://note", size: int = 9000) -> Attachment:
    return Attachment(url, "voice-message.ogg", "audio/ogg", size, voice=True)


def press(data: str, user: str = OWNER, *, direct: bool = True, press_id: str = "i1") -> Press:
    return Press(press_id, "tok", CHAT, "m1", user, "Owner", direct, data)


async def settle(rounds: int = 20) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0.01)
