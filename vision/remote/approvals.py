"""Approvals from the phone: a gate request as a message with Yes and Not now.

The message carries the exact detail of what will be done. It has buttons
only when the tool may be approved from the phone (Settings, Phone) and the
detail fits in full; otherwise it says why it must be approved at the Mac.
`shell` is always approved at the Mac.

A press counts only from the paired owner, in the direct chat, on a request
that is still open, for a tool the phone may approve. The press is answered
at once (within the service's deadline), then the decision is published as
the same `gate.decision` the window sends, so the gate audits it and
publishes `gate.resolved` exactly as for an answer at the Mac. When the
request ends, however it ended, the message is edited to say so.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from vision.core.events import GateChoice, GateDecision, GateOutcome, GateRequest, GateResolved
from vision.remote.host import PHONE_NEVER
from vision.remote.link import Link
from vision.remote.transport import Button, Press, Unreachable

log = logging.getLogger(__name__)

PREFIX = "gate"
DETAIL_ROOM = 1200
"""Characters left for the detail; a longer one is approved at the Mac."""
GONE = "This request is no longer open, so nothing was done from here."


@dataclass(slots=True)
class _Sent:
    chat_id: str
    message_id: str
    head: str
    """The request without its last line (the buttons' instruction)."""
    by_phone: GateChoice | None = None


def button_data(request_id: str, choice: GateChoice) -> str:
    return f"{PREFIX}:{request_id}:{choice}"


def parse_data(data: str) -> tuple[str, GateChoice] | None:
    prefix, _, rest = data.partition(":")
    request_id, _, choice = rest.rpartition(":")
    if prefix != PREFIX or not request_id or choice not in ("allow", "deny"):
        return None
    return request_id, "allow" if choice == "allow" else "deny"


def outcome_words(outcome: GateOutcome, by_phone: GateChoice | None) -> str:
    where = " from the phone" if by_phone is not None else ""
    if outcome == "allow":
        return f"Approved{where}; it ran."
    if outcome == "deny":
        return f"Declined{where}; it did not run."
    return "Nobody answered in time, so it did not run."


class Approvals:
    def __init__(self, link: Link) -> None:
        self._link = link
        self._sent: dict[str, _Sent] = {}

    def head(self, req: GateRequest) -> str:
        return f"Needs your yes: {req.summary}\n\nWhat will be done ({req.tool}):\n{req.detail}"

    def mac_only_reason(self, req: GateRequest) -> str | None:
        """Why this request must be approved at the Mac, or None when the phone may."""
        if req.tool in PHONE_NEVER:
            return f"Approve this at the Mac: {req.tool} is never approved from the phone."
        if not self._link.phone_may_approve(req.tool):
            return f"Approve this at the Mac: {req.tool} is not one of the tools the phone may approve (Settings, Phone)."
        if len(req.detail) > DETAIL_ROOM:
            return "Approve this at the Mac: the detail is too long to show here in full."
        return None

    async def request(self, req: GateRequest) -> None:
        """Send the request; the notifier has decided it should go (requests that need a yes)."""
        state = self._link.state()
        if not state.paired:
            return
        head = self.head(req) if len(req.detail) <= DETAIL_ROOM else self.head(req.model_copy(update={"detail": req.detail[:DETAIL_ROOM] + "…"}))
        why = self.mac_only_reason(req)
        transport = self._link.transport
        if why is not None:
            message_id = await transport.send(state.chat_id, f"{head}\n\n{why}")
        else:
            seconds = max(0, round(req.expires_at - time.time()))
            buttons = [Button(button_data(req.id, "allow"), "Yes", "yes"), Button(button_data(req.id, "deny"), "Not now", "no")]
            message_id = await transport.send_buttons(state.chat_id, f"{head}\n\nAnswer within {seconds} seconds.", buttons)
        self._sent[req.id] = _Sent(state.chat_id, message_id, head)

    async def resolved(self, res: GateResolved) -> None:
        sent = self._sent.pop(res.id, None)
        if sent is None:
            return
        await self._link.transport.edit(sent.chat_id, sent.message_id, f"{sent.head}\n\n{outcome_words(res.decision, sent.by_phone)}")

    async def press(self, p: Press) -> None:
        link = self._link
        try:
            if not (p.direct and link.is_owner(p.user_id)):
                await link.transport.acknowledge(p, None)
                await link.refused(p.user_id, p.user_name, "button", "button pressed by someone other than the paired owner")
                return
            parsed = parse_data(p.data)
            if parsed is None:
                await link.transport.acknowledge(p, None)
                return
            request_id, choice = parsed
            sent = self._sent.get(request_id)
            req = link.host.open_request(request_id)
            if sent is None or req is None:
                await link.transport.acknowledge(p, GONE)
                return
            why = self.mac_only_reason(req)
            if why is not None:
                await link.transport.acknowledge(p, f"{sent.head}\n\n{why}")
                return
            sent.by_phone = choice
            words = "Approved from the phone. Running it now…" if choice == "allow" else "Declined from the phone."
            await link.transport.acknowledge(p, f"{sent.head}\n\n{words}")
            link.host.bus.publish(GateDecision(id=request_id, decision=choice))
        except Unreachable as exc:
            log.warning("could not answer a button press: %s", exc)
