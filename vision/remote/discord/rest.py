"""Discord's HTTP API with `httpx`: the bot token in a header, rate limits obeyed.

- Every call carries `Authorization: Bot <token>`, except interaction
  callbacks, which are authorised by the interaction's own token in the path.
  The bot token is never put in a URL, an exception or a log line.
- Rate limits: a route whose `X-RateLimit-Remaining` reached 0 waits
  `X-RateLimit-Reset-After` seconds before its next call; a 429 waits its
  `retry_after` (or `Retry-After`) and tries again, at most `MAX_TRIES` times.
- 401 raises `TokenRefused`. A network failure or a 5xx is tried again after a
  short pause, then raises `Unreachable`. Other refusals raise `DiscordError`
  with Discord's JSON error code.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from vision import __version__
from vision.remote.transport import TokenRefused, Unreachable

log = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
TIMEOUT_S = 20.0
MAX_TRIES = 4
USER_AGENT = f"DiscordBot (https://openquestai.invalid, {__version__})"
"""Discord asks for `DiscordBot ($url, $version)`; the project has no public URL yet."""
_IDS = re.compile(r"/(messages|interactions)/\d+(/[^/]+)?")


class DiscordError(Unreachable):
    """Discord refused a request. `code` is its JSON error code (50007 and the like)."""

    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(f"Discord refused the request ({status}, code {code}): {message}")
        self.status = status
        self.code = code


def route_key(method: str, path: str) -> str:
    """The route a rate limit belongs to: the path with message and interaction ids generalised."""
    return f"{method} {_IDS.sub(lambda m: f'/{m.group(1)}/:id', path)}"


class DiscordRest:
    def __init__(
        self,
        token: str,
        *,
        base: str = API_BASE,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._token = token
        self._sleep = sleep
        self.base = base.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT_S)
        self._owns_client = client is None
        self._blocked: dict[str, float] = {}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        data: dict[str, str] | None = None,
        auth: bool = True,
    ) -> Any:
        """One API call; the decoded JSON answer, or None for an empty one."""
        key = route_key(method, path)
        headers = {"User-Agent": USER_AGENT}
        if auth:
            headers["Authorization"] = f"Bot {self._token}"
        for attempt in range(1, MAX_TRIES + 1):
            wait = self._blocked.get(key, 0.0) - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            try:
                res = await self._client.request(
                    method, self.base + path, json=json, files=files, data=data, headers=headers
                )
            except httpx.HTTPError as exc:
                if attempt == MAX_TRIES:
                    raise Unreachable(f"Discord could not be reached ({type(exc).__name__}).") from None
                await self._sleep(min(8.0, 0.5 * 2**attempt))
                continue
            self._note_limits(key, res)
            if res.status_code == 429:
                if attempt == MAX_TRIES:
                    raise Unreachable("Discord kept asking to slow down.")
                await self._sleep(retry_after(res))
                continue
            if res.status_code >= 500:
                if attempt == MAX_TRIES:
                    raise Unreachable(f"Discord answered {res.status_code}.")
                await self._sleep(min(8.0, 0.5 * 2**attempt))
                continue
            if res.status_code == 401:
                raise TokenRefused("Discord refused the bot token.")
            if res.status_code >= 400:
                body = _json(res)
                raise DiscordError(res.status_code, int(body.get("code", 0)), str(body.get("message", "")))
            if not res.content:
                return None
            try:
                return res.json()
            except ValueError:
                raise Unreachable("Discord's answer was not JSON.") from None
        raise Unreachable("Discord could not be reached.")

    async def download(self, url: str, limit: int) -> bytes:
        """An attachment from Discord's CDN, without the bot token. Raises `Unreachable`."""
        try:
            async with self._client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as res:
                if res.status_code != 200:
                    raise Unreachable(f"The attachment could not be downloaded ({res.status_code}).")
                chunks: list[bytes] = []
                size = 0
                async for chunk in res.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise Unreachable("The attachment is too large.")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise Unreachable(f"The attachment could not be downloaded ({type(exc).__name__}).") from None

    def _note_limits(self, key: str, res: httpx.Response) -> None:
        remaining = res.headers.get("x-ratelimit-remaining")
        reset_after = res.headers.get("x-ratelimit-reset-after")
        if remaining == "0" and reset_after is not None:
            try:
                self._blocked[key] = time.monotonic() + float(reset_after)
            except ValueError:
                return


def retry_after(res: httpx.Response) -> float:
    """Seconds to wait after a 429: `retry_after` in the body, else `Retry-After`, else 1."""
    body = _json(res)
    value = body.get("retry_after", res.headers.get("retry-after", 1.0))
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 1.0


def _json(res: httpx.Response) -> dict[str, Any]:
    try:
        body = res.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {"value": body}
