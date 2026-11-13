"""What is sent to the paired owner unasked, each kind by its choice in Settings, Phone
(`vision.remote.rules`: always, only when the owner is away from the Mac, or never):

- automation results (`automation.finished`);
- notices of level warn or error (`notice`), except those about the phone
  channel itself, which could not arrive anyway;
- requests that need a yes (`gate.request`), handed to `Approvals`, which
  also edits each one when it ends (`gate.resolved`);
- a line saying an agent's proposal waits at the Mac (`proposal`, by the
  approvals choice), with no buttons: proposals are decided in the window;
- the host's report of every finished job, wherever it was handed off from
  (`job_result`, called by the daemon's job reporter, not from the bus); a
  job handed off from the phone reports there unless job results are never.

These are what the assistant does by itself, so by default every kind is
always sent, to the phone as well as the app. A reply to something typed or
said at the Mac is never sent: it is answered at the Mac. (A reply to the
phone goes back by the channel itself, `PhoneChannel`.) Presence matters only
for a kind the owner sets to `away`; it is read fresh for that decision
(`Host.presence`). Nothing is sent before
pairing; messages go through the `Outbox`, which sends each one once and
retries one that did not arrive a few times before dropping it. The result
of a turn in which `send_to_phone` already messaged the phone is not sent
again.
"""

from __future__ import annotations

import logging

from vision.core.events import AutomationFinished, AutomationStarted, Event, GateRequest, GateResolved, Notice
from vision.remote.approvals import Approvals
from vision.remote.link import Link
from vision.remote.outbox import DROPPED, Outbox
from vision.remote.rules import FIELDS, Kind
from vision.remote.text import clip
from vision.remote.transport import Unreachable

log = logging.getLogger(__name__)

TYPES = frozenset(
    {AutomationStarted.TYPE, AutomationFinished.TYPE, Notice.TYPE, GateRequest.TYPE, GateResolved.TYPE}
)
REPLY_ROOM = 1500
APP_ONLY = (DROPPED, "The phone channel stopped")
"""Notices about the channel itself stay in the app."""

_RESULT = {
    "ok": "ran",
    "failed": "failed",
    "interrupted": "was interrupted",
    "needed_approval": "needed a yes that nobody gave",
}


def automation_line(event: AutomationFinished) -> str:
    did = _RESULT.get(event.status, event.status)
    reply = clip(event.reply.strip(), REPLY_ROOM)
    return f"Automation “{event.name}” {did}." + (f"\n\n{reply}" if reply else "")


def notice_line(event: Notice) -> str:
    return f"{'Error' if event.level == 'error' else 'Warning'}: {event.text}"


class Notifier:
    def __init__(self, link: Link, approvals: Approvals, outbox: Outbox) -> None:
        self._link = link
        self._approvals = approvals
        self._outbox = outbox
        self._started: dict[str, float] = {}
        """When each automation running now began, so its result knows what happened during it."""

    async def run(self) -> None:
        """Follow the bus until cancelled."""
        async with self._link.host.bus.subscribe(TYPES) as sub:
            async for event in sub:
                try:
                    await self.handle(event)
                except Unreachable as exc:
                    log.info("phone notification not sent (%s): %s", event.TYPE, exc)
                except Exception:
                    log.exception("phone notification failed (%s)", event.TYPE)

    def wants(self, kind: Kind) -> bool:
        """Paired, and this kind's choice allows it with the owner where they are now."""
        state = self._link.state()
        if not state.paired:
            return False
        choice = getattr(state, FIELDS[kind])
        return choice == "always" or (choice == "away" and self._link.host.presence().away)  # read only when it matters

    async def handle(self, event: Event) -> None:
        match event:
            case GateRequest() if self.wants("approvals"):
                await self._approvals.request(event)
            case GateResolved():
                await self._approvals.resolved(event)
            case AutomationStarted():
                self._started[event.id] = event.ts
            case AutomationFinished():
                started = self._started.pop(event.id, event.ts)
                if self.wants("automations") and not self._outbox.pinged_since(started):
                    await self._outbox.send(f"automation:{event.id}:{started}", automation_line(event))
            case Notice(level="warn" | "error") if not event.text.startswith(APP_ONLY) and self.wants("warnings"):
                await self._outbox.send(f"notice:{event.ts}:{event.text}", notice_line(event))

    async def proposal(self, key: str, text: str) -> None:
        """An agent's proposal arrived: a short line pointing at the Mac, by the approvals choice.
        It never carries buttons: proposals are decided in the window only."""
        if self.wants("approvals"):
            await self._outbox.send(key, text)

    async def job_result(self, job_id: str, text: str, *, from_phone: bool, started_at: float) -> None:
        """The host's words about a finished job; `started_at` is when the report's turn began."""
        state = self._link.state()
        if not text.strip() or state.notify_jobs == "never":
            return
        if not (from_phone or self.wants("jobs")) or self._outbox.pinged_since(started_at):
            return
        await self._outbox.send(f"job:{job_id}", text)
