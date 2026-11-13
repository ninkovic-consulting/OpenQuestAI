"""The phone channel above the transport: who is served, and what a message does.

Only direct messages count; anything from a server is ignored. Until the
channel is paired, and for everyone but the paired owner afterwards, a
message runs nothing and reveals nothing: it gets one fixed line (at most once
a minute per person) and the attempt is written to the audit log. A six-digit
message from someone while a pairing code is live is checked against it; a
match makes them the owner.

From the owner:

- `status`, `stop` and `help` (or `start`), as plain words, with or without
  a leading slash;
- a voice note: downloaded, decoded and transcribed locally, then its words
  are the turn;
- any other text: a turn.

Turns wait their turn: each is queued (at most five waiting) and starts only
when the assistant is idle, through `Host.run_turn`, so it never overlaps a
turn at the Mac or an automation. "Typing" shows from the moment a message is
accepted until its reply is sent. No command goes around the gate; `stop`
only interrupts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from vision.core.events import Notice
from vision.core.interfaces import TurnRecord
from vision.remote import audio, words
from vision.remote.approvals import Approvals
from vision.remote.ears import Ears
from vision.remote.host import TurnsBusy
from vision.remote.link import Link
from vision.remote.notify import Notifier
from vision.remote.outbox import Outbox
from vision.remote.pairing import looks_like_code
from vision.remote.text import clip
from vision.remote.transport import Attachment, Handlers, Incoming, Unreachable

log = logging.getLogger(__name__)

MAX_WAITING = 5
IDLE_POLL_S = 0.5
TYPING_EVERY_S = 8.0
"""The service shows typing for about ten seconds per call."""
REFUSE_EVERY_S = 60.0
MAX_VOICE_BYTES = 20 * 1024 * 1024
VOICE_REPLY_ROOM = 800
COMMANDS = frozenset({"status", "stop", "help", "start"})


@dataclass(frozen=True, slots=True)
class _Job:
    chat_id: str
    text: str
    voice: bool


def command(text: str) -> str | None:
    word = text.strip().lower().lstrip("/").rstrip(".!?")
    return word if word in COMMANDS else None


class PhoneChannel:
    def __init__(
        self,
        link: Link,
        ears: Ears,
        decoders: list[audio.Decoder],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._link = link
        self._ears = ears
        self._decoders = decoders
        self._clock = clock
        self._queue: asyncio.Queue[_Job] = asyncio.Queue(maxsize=MAX_WAITING)
        self._job: asyncio.Task[None] | None = None
        self._refused_at: dict[str, float] = {}
        self.approvals = Approvals(link)
        self.outbox = Outbox(link)
        self.notifier = Notifier(link, self.approvals, self.outbox)

    def handlers(self, online: Callable[[bool], None]) -> Handlers:
        return Handlers(message=self.on_message, press=self.approvals.press, online=online)

    @property
    def waiting(self) -> int:
        return self._queue.qsize()

    async def run(self) -> None:
        """Serve queued turns and send notifications until cancelled."""
        await asyncio.gather(self._serve_queue(), self.notifier.run())

    # ------------------------------------------------------------ incoming

    async def on_message(self, m: Incoming) -> None:
        if not m.direct:
            return
        try:
            if self._link.is_owner(m.user_id):
                await self._owner(m)
            else:
                await self._stranger(m)
        except Unreachable as exc:
            log.info("could not answer a phone message: %s", exc)

    async def _stranger(self, m: Incoming) -> None:
        link = self._link
        kind = "voice" if m.attachments else "text"
        if not link.state().paired and looks_like_code(m.text):
            result = link.pairing.check(m.text)
            if result == "paired":
                await self._pair(m)
                return
            await link.refused(m.user_id, m.user_name, "code", f"pairing code {result}")
        else:
            why = "not the paired owner" if link.state().paired else "not paired yet"
            await link.refused(m.user_id, m.user_name, kind, why)
        now = self._clock()
        if now - self._refused_at.get(m.user_id, float("-inf")) >= REFUSE_EVERY_S:
            self._refused_at[m.user_id] = now
            await link.transport.send(m.chat_id, words.PRIVATE)

    async def _pair(self, m: Incoming) -> None:
        state = self._link.state()
        state.owner_id, state.owner_name, state.chat_id = m.user_id, m.user_name, m.chat_id
        state.paired_at = time.time()
        await self._link.save()
        self._link.host.bus.publish(Notice(level="info", text=words.paired_notice(m.user_name)))
        await self._link.transport.send(m.chat_id, words.paired(self._link.host.status().name))

    async def _owner(self, m: Incoming) -> None:
        state = self._link.state()
        if m.chat_id != state.chat_id:
            state.chat_id = m.chat_id
            await self._link.save()
        transport = self._link.transport
        voice = next((a for a in m.attachments if a.voice or a.content_type.startswith("audio/")), None)
        match command(m.text):
            case "status":
                await transport.send(m.chat_id, words.status_line(self._link.host.status(), self.waiting))
            case "stop":
                await transport.send(m.chat_id, await self.stop())
            case "help" | "start":
                await transport.send(m.chat_id, words.help_line())
            case None if voice is not None:
                await self._voice_note(m.chat_id, voice)
            case None if m.text.strip():
                await self._enqueue(_Job(m.chat_id, m.text.strip(), voice=False))
            case _:
                await transport.send(m.chat_id, words.ONLY_TEXT)

    async def stop(self) -> str:
        """Drop the waiting messages and interrupt the reply in progress."""
        dropped = 0
        while not self._queue.empty():
            self._queue.get_nowait()
            dropped += 1
        busy = self._link.host.busy()
        if busy:
            await self._link.host.interrupt()
        job = self._job
        waiting_job = job is not None and not job.done() and not busy
        if waiting_job and job is not None:
            job.cancel()
        return words.STOPPED if dropped or busy or waiting_job else words.NOTHING_TO_STOP

    async def _enqueue(self, job: _Job) -> None:
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            await self._link.transport.send(job.chat_id, words.TOO_MANY)
            return
        await self._link.transport.typing(job.chat_id)

    # ------------------------------------------------------------ voice notes

    async def _voice_note(self, chat_id: str, note: Attachment) -> None:
        transport = self._link.transport
        if note.size > MAX_VOICE_BYTES:
            await transport.send(chat_id, words.VOICE_TOO_LONG)
            return
        if not await asyncio.to_thread(self._ears.installed):
            await transport.send(chat_id, words.VOICE_NO_MODELS)
            return
        decoder = await asyncio.to_thread(audio.first_available, self._decoders)
        if decoder is None:
            await transport.send(chat_id, words.VOICE_NO_DECODER)
            return
        await transport.typing(chat_id)
        try:
            data = await transport.fetch(note, MAX_VOICE_BYTES)
        except Unreachable:
            await transport.send(chat_id, words.VOICE_NOT_FETCHED)
            return
        try:
            sound = await asyncio.to_thread(decoder.decode, data)
        except audio.DecodeFailed as exc:
            log.info("voice note not decoded by %s: %s", decoder.name, exc)
            await transport.send(chat_id, words.VOICE_NOT_DECODED)
            return
        try:
            heard = (await self._ears.transcribe(sound)).strip()
        except Exception:
            log.exception("voice note not transcribed")
            await transport.send(chat_id, words.VOICE_NOT_HEARD)
            return
        if not heard:
            await transport.send(chat_id, words.VOICE_EMPTY)
            return
        await transport.send(chat_id, words.heard(heard))
        await self._enqueue(_Job(chat_id, heard, voice=True))

    async def _voice_reply(self, chat_id: str, reply: str) -> None:
        try:
            sound, rate = await self._ears.speak(clip(reply, VOICE_REPLY_ROOM))
            ogg = await asyncio.to_thread(audio.encode_voice, sound, rate)
            if ogg is None:
                return
            shape = await asyncio.to_thread(audio.waveform, sound)
            await self._link.transport.send_voice(chat_id, ogg, len(sound) / rate, shape)
        except Unreachable as exc:
            log.info("voice reply not sent: %s", exc)
        except Exception:
            log.exception("voice reply failed; the text was sent")

    # ------------------------------------------------------------ turns

    async def _serve_queue(self) -> None:
        while True:
            job = await self._queue.get()
            self._job = asyncio.create_task(self._serve(job))
            await asyncio.gather(self._job, return_exceptions=True)
            self._job = None

    async def _serve(self, job: _Job) -> None:
        typing = asyncio.create_task(self._keep_typing(job.chat_id))
        try:
            record = await self._run_when_idle(job.text)
        finally:
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)
        reply = record.reply.strip() or words.NO_REPLY
        if record.status == "interrupted":
            reply = f"{reply}\n\n{words.CUT_SHORT}" if record.reply.strip() else words.CUT_SHORT
        try:
            await self._link.transport.send(job.chat_id, reply)
        except Unreachable as exc:
            log.info("phone reply not sent: %s", exc)
            return
        if job.voice and self._link.state().voice_replies and record.reply.strip():
            await self._voice_reply(job.chat_id, record.reply)

    async def _run_when_idle(self, text: str) -> TurnRecord:
        host = self._link.host
        while True:
            while host.busy():
                await asyncio.sleep(IDLE_POLL_S)
            try:
                return await host.run_turn(text, speak=self._link.state().speak_on_mac)
            except TurnsBusy:
                await asyncio.sleep(IDLE_POLL_S)

    async def _keep_typing(self, chat_id: str) -> None:
        while True:
            try:
                await self._link.transport.typing(chat_id)
            except Unreachable:
                pass
            await asyncio.sleep(TYPING_EVERY_S)
