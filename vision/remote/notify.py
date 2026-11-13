"""Notifications to the paired owner, each with its own switch in Settings, Phone:

- automation results (`automation.finished`);
- notices of level warn or error (`notice`);
- requests that need a yes (`gate.request`), handed to `Approvals`, which
  also edits each one when it ends (`gate.resolved`);
- the host's report of a job that was handed off from a phone turn
  (`job_result`, called by the daemon's job reporter, not from the bus).

Nothing is sent before pairing. A message that cannot be sent (the service
is unreachable) is logged and dropped, never retried into a flood later.
"""

from __future__ import annotations

import logging

from vision.core.events import AutomationFinished, Event, GateRequest, GateResolved, Notice
from vision.remote.approvals import Approvals
from vision.remote.link import Link
from vision.remote.text import clip
from vision.remote.transport import Unreachable

log = logging.getLogger(__name__)

TYPES = frozenset({AutomationFinished.TYPE, Notice.TYPE, GateRequest.TYPE, GateResolved.TYPE})
REPLY_ROOM = 1500

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
    def __init__(self, link: Link, approvals: Approvals) -> None:
        self._link = link
        self._approvals = approvals

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

    async def job_result(self, text: str) -> None:
        """The host's words about a finished job, when paired and `notify_jobs` is on."""
        state = self._link.state()
        if not (state.paired and state.notify_jobs and text.strip()):
            return
        try:
            await self._link.transport.send(state.chat_id, clip(text.strip(), REPLY_ROOM))
        except Unreachable as exc:
            log.info("job report not sent to the phone: %s", exc)

    async def handle(self, event: Event) -> None:
        state = self._link.state()
        match event:
            case GateRequest():
                await self._approvals.request(event)
            case GateResolved():
                await self._approvals.resolved(event)
            case AutomationFinished() if state.paired and state.notify_automations:
                await self._link.transport.send(state.chat_id, automation_line(event))
            case Notice(level="warn" | "error") if state.paired and state.notify_warnings:
                await self._link.transport.send(state.chat_id, notice_line(event))
