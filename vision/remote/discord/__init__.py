"""The Discord transport: the Gateway over `websockets` and the HTTP API over `httpx`.

`VISION_DISCORD_API` replaces the API base URL (tests and the local fake
only); attachments are then also accepted from that host.
"""

from __future__ import annotations

import os

from vision.remote.discord.rest import API_BASE
from vision.remote.discord.transport import DiscordTransport

API_ENV = "VISION_DISCORD_API"


def make_transport(token: str) -> DiscordTransport:
    return DiscordTransport(token, base=os.environ.get(API_ENV) or API_BASE)


__all__ = ["API_ENV", "DiscordTransport", "make_transport"]
