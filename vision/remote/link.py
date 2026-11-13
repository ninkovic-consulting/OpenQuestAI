"""What the parts of the phone channel share: the daemon, the settings, the
connection, the pairing code, and the audit line for refused attempts."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from vision.core.interfaces import AuditRecord
from vision.remote.host import PHONE_NEVER, PHONE_OFF_BY_DEFAULT, Host
from vision.remote.pairing import Pairing
from vision.remote.store import PhoneState
from vision.remote.transport import Transport, Unreachable

AUDIT_TOOL = "phone"


@dataclass(slots=True)
class Link:
    host: Host
    pairing: Pairing
    state: Callable[[], PhoneState]
    save: Callable[[], Awaitable[None]]
    current: Callable[[], Transport | None]

    @property
    def transport(self) -> Transport:
        """The connected transport. Raises `Unreachable` while there is none."""
        transport = self.current()
        if transport is None:
            raise Unreachable("The phone channel is not connected.")
        return transport

    def is_owner(self, user_id: str) -> bool:
        state = self.state()
        return state.paired and user_id == state.owner_id

    def phone_may_approve(self, tool: str) -> bool:
        if tool in PHONE_NEVER:
            return False
        allowed = self.state().phone_tools
        if allowed is None:
            return tool not in PHONE_OFF_BY_DEFAULT
        return tool in allowed

    async def refused(self, user_id: str, user_name: str, kind: str, why: str) -> None:
        """Write a refused attempt to the audit log: who and what kind, never the words."""
        await self.host.audit(
            AuditRecord(
                ts=time.time(),
                tool=AUDIT_TOOL,
                args={"user_id": user_id, "user_name": user_name, "kind": kind},
                tier="owner",
                decision="deny",
                result=why,
            )
        )
