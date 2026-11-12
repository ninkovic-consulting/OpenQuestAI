"""The local brain over HTTP (`[brain] local_backend = "openai"`): any
OpenAI-compatible chat endpoint, streamed, no tools.

The server is `[brain] local_base_url` (Ollama's address by default) and the
model is `local_model`.
Pointing `local_base_url` at LM Studio, OpenRouter or another compatible
server is a config change. If that server needs a key, set
`[brain] local_api_key_env` to the name of the environment variable holding
it; the key is sent as a bearer token and never logged.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any

import httpx

from vision.brains.pump import Emit, Pump
from vision.core.config import Config
from vision.core.events import BrainName
from vision.core.interfaces import BrainError, BrainEvent, Memory, TextDelta, TurnDone

log = logging.getLogger(__name__)

DEFAULT_HISTORY_TURNS = 20
Message = dict[str, str]


class LocalModelError(Exception):
    def __init__(self, error: BrainError) -> None:
        super().__init__(error.message)
        self.error = error


def _status_error(status: int) -> BrainError:
    if status in (401, 403):
        return BrainError("auth", f"The local model server refused the key (HTTP {status}).", False)
    if status == 429:
        return BrainError("rate_limit", "The local model server is rate limited.", True)
    if status == 404:
        return BrainError("bad_request", "The local model is not installed on the server.", False)
    if status >= 500:
        return BrainError("unavailable", f"The local model server failed (HTTP {status}).", True)
    return BrainError("bad_request", f"The local model server rejected the request (HTTP {status}).", False)


@dataclass
class _Turn:
    user: Message
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class LocalBrain:
    def __init__(
        self, config: Config, memory: Memory, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._config = config
        self._transport = transport
        self._memory = memory
        extra = config.brain.model_extra or {}
        self._max_turns = max(1, int(extra.get("history_turns", DEFAULT_HISTORY_TURNS)))
        self._key_env: str | None = extra.get("local_api_key_env")
        self._client: httpx.AsyncClient | None = None
        self._history: list[tuple[Message, Message]] = []
        self._pump = Pump()

    @property
    def name(self) -> BrainName:
        return "local"

    @property
    def model(self) -> str:
        return self._config.brain.local_model

    async def start(self) -> None:
        headers = {}
        key = os.environ.get(self._key_env) if self._key_env else None
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self._client = httpx.AsyncClient(
            base_url=self._config.brain.local_base_url.rstrip("/"),
            headers=headers,
            timeout=self._config.brain.request_timeout_s,
            transport=self._transport,
        )

    async def interrupt(self) -> None:
        self._pump.stop()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        turn = _Turn(user={"role": "user", "content": text})
        error: BrainError | None = None
        said: list[str] = []
        try:
            async with aclosing(self._pump.run(lambda emit: self._stream(turn, emit))) as events:
                async for event in events:
                    if isinstance(event, TextDelta):
                        said.append(event.text)
                    yield event
        except LocalModelError as exc:
            error = exc.error
        except httpx.TimeoutException:
            error = BrainError("timeout", "The local model took too long to answer.", True)
        except httpx.TransportError:
            error = BrainError("unavailable", "The local model server is not running.", True)
        except (ValueError, KeyError, TypeError):
            error = BrainError("internal", "The local model server sent a malformed reply.", False)
        finally:
            if error is None:
                self._commit(turn.user, "".join(said).strip())
        if error is not None:
            yield error
            return
        stop = "interrupted" if self._pump.interrupted else turn.stop_reason
        yield TurnDone(self.model, turn.input_tokens, turn.output_tokens, stop)

    async def _stream(self, turn: _Turn, emit: Emit) -> None:
        if self._client is None:
            raise LocalModelError(BrainError("internal", "The local brain was not started.", False))
        messages: list[Message] = []
        core = self._memory.core()
        if core:
            messages.append({"role": "system", "content": core})
        for user, reply in self._history:
            messages += [user, reply]
        messages.append(turn.user)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": self._config.brain.max_output_tokens,
            "stream_options": {"include_usage": True},
        }
        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            if response.status_code >= 400:
                raise LocalModelError(_status_error(response.status_code))
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                self._handle_chunk(turn, emit, json.loads(data))

    def _handle_chunk(self, turn: _Turn, emit: Emit, chunk: dict[str, Any]) -> None:
        usage = chunk.get("usage")
        if usage:
            turn.input_tokens = int(usage.get("prompt_tokens") or 0)
            turn.output_tokens = int(usage.get("completion_tokens") or 0)
        for choice in chunk.get("choices") or []:
            content = (choice.get("delta") or {}).get("content")
            if content:
                emit(TextDelta(content))
            finish = choice.get("finish_reason")
            if finish:
                turn.stop_reason = "end_turn" if finish == "stop" else finish

    def _commit(self, user: Message, said: str) -> None:
        if not said:
            return
        self._history.append((user, {"role": "assistant", "content": said}))
        del self._history[: -self._max_turns]
