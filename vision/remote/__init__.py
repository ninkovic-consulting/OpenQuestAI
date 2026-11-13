"""The phone channel: talk to the assistant from a phone, through a chat service.

    phone = make_phone(daemon)      # no I/O here
    await phone.start()             # loads phone.json, connects when a token is stored
    app.include_router(build_router(phone), prefix="/api", dependencies=auth)

Layers, top down:

- `service.Phone`: lifetime, settings, the token, pairing codes; the routes.
- `channel.PhoneChannel`: who is served (pairing, the owner), commands,
  voice notes, and turns queued until the assistant is idle;
  `notify.Notifier` and `approvals.Approvals`: what is sent unasked, by the
  owner's choices and whether they are at the Mac (`rules`), and gate
  requests answered with buttons; `outbox.Outbox`: each message once, retried
  a few times when it does not arrive.
- `tools`: `send_to_phone`, the host's way to message the phone on purpose.
- `transport.Transport`: one chat service. `discord.DiscordTransport` is the
  only one: the Gateway over `websockets`, the HTTP API over `httpx`, direct
  messages only. Nothing on the Mac listens for the internet.

The bot token lives in the Keychain (`token.py`); everything else in
`$VISION_HOME/phone.json` (`store.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vision.remote.audio import default_decoders
from vision.remote.discord import make_transport
from vision.remote.ears import LocalEars
from vision.remote.host import DaemonHost
from vision.remote.routes import build_router
from vision.remote.service import Phone
from vision.remote.store import FILE_NAME
from vision.remote.token import KeychainToken
from vision.remote.tools import build_tools

if TYPE_CHECKING:
    from vision.app import Daemon


def make_phone(daemon: Daemon) -> Phone:
    host = DaemonHost(daemon)
    return Phone(
        host,
        daemon.config.paths.home,
        tokens=KeychainToken(),
        transports=make_transport,
        ears=LocalEars(host, lambda: daemon.config),
        decoders=default_decoders(),
    )


__all__ = ["FILE_NAME", "Phone", "build_router", "build_tools", "make_phone"]
