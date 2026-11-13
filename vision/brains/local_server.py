"""The local model over HTTP (`[brain] local_backend = "openai"`): any OpenAI-compatible
chat server (LM Studio, Ollama, llama.cpp's server and the like), streamed.

The server is `[brain] local_base_url` (Ollama's address by default) and the
model is `local_model`, the server's own name for it. If the server needs a
key, `[brain] local_api_key_env` names the environment variable holding it;
it is sent as a bearer token and never logged.

Tools go out as the standard `tools` list and come back as `tool_calls`
deltas, gathered by index. A server that refuses a request with tools (an
HTTP 400 or 422) is asked again without them, and the model counts as
talk-only from then on.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from vision.brains.local_chat import Call, Message, OnText, Reply, Request, Status, Who, openai_tools
from vision.brains.local_errors import LocalModelError
from vision.core.config import Config
from vision.core.interfaces import BrainError

log = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 5.0
TOOLS_REFUSED = frozenset({400, 422})


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


def server_key(config: Config) -> str | None:
    env = (config.brain.model_extra or {}).get("local_api_key_env")
    return os.environ.get(env) if isinstance(env, str) and env else None


@dataclass(frozen=True, slots=True)
class Probe:
    """What a server said when asked for its models."""

    ok: bool
    models: list[str] = field(default_factory=list)
    message: str = ""


async def probe(
    base_url: str, key: str | None, *, transport: httpx.AsyncBaseTransport | None = None
) -> Probe:
    """Ask the server at `base_url` for its models (`GET /models`). Never raises."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=PROBE_TIMEOUT_S, transport=transport
        ) as client:
            response = await client.get("/models")
    except httpx.TimeoutException:
        return Probe(False, message=f"The server at {base_url} did not answer in time.")
    except httpx.HTTPError:
        return Probe(False, message=f"Nothing answers at {base_url}. Is the server running?")
    if response.status_code >= 400:
        return Probe(False, message=_status_error(response.status_code).message)
    try:
        rows = response.json().get("data") or []
        models = [str(r["id"]) for r in rows if isinstance(r, dict) and r.get("id")]
    except (ValueError, AttributeError, KeyError):
        return Probe(False, message=f"The server at {base_url} does not speak the OpenAI format.")
    return Probe(True, models, f"The server answers and lists {len(models)} model(s).")


def _wire(messages: list[Message]) -> list[Message]:
    """Messages as the server reads them: tool-call arguments as JSON text."""
    out: list[Message] = []
    for m in messages:
        calls = m.get("tool_calls")
        if calls:
            m = {
                **m,
                "tool_calls": [
                    {**c, "function": {**c["function"], "arguments": json.dumps(c["function"]["arguments"])}}
                    for c in calls
                ],
            }
        out.append(m)
    return out


class ServerBackend:
    """One model on an OpenAI-compatible server."""

    def __init__(
        self, config: Config, repo: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._config = config
        self.model = repo
        self._base_url = config.brain.local_base_url.rstrip("/")
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._tools: bool | None = None
        self._halt = False
        self.changed: Callable[[], None] = lambda: None

    @property
    def known_tools(self) -> bool | None:
        return self._tools

    def status(self) -> Status:
        """The server holds the model; nothing is loaded in this process."""
        return Status()

    async def preload(self) -> None:
        """The server loads its own models."""

    def follow_policy(self) -> None:
        """Nothing is kept in this process."""

    async def start(self) -> None:
        key = server_key(self._config)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=self._config.brain.request_timeout_s,
            transport=self._transport,
        )

    def stop(self) -> None:
        self._halt = True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def ready(self) -> str | None:
        found = await probe(self._base_url, server_key(self._config), transport=self._transport)
        if not found.ok:
            return found.message
        if found.models and self.model not in found.models:
            return f"The server at {self._base_url} has no model called {self.model}."
        return None

    async def can_call_tools(self) -> bool:
        """Assumed until the server refuses tools once."""
        return self._tools is not False

    async def generate(self, request: Request, on_text: OnText | None, who: Who = "host") -> Reply:
        if self._client is None:
            raise LocalModelError(BrainError("internal", "The local brain was not started.", False))
        self._halt = False
        tools = request.tools if self._tools is not False else []
        try:
            try:
                return await self._stream(request, tools, on_text)
            except _ToolsRefused:
                log.warning("the local model server refused tools; continuing without them")
                self._tools = False
                return await self._stream(request, [], on_text)
        except httpx.TimeoutException:
            raise LocalModelError(BrainError("timeout", "The local model took too long to answer.", True)) from None
        except httpx.TransportError:
            raise LocalModelError(BrainError("unavailable", "The local model server is not running.", True)) from None
        except (ValueError, KeyError, TypeError):
            raise LocalModelError(BrainError("internal", "The local model server sent a malformed reply.", False)) from None

    async def _stream(self, request: Request, tools: list[Any], on_text: OnText | None) -> Reply:
        assert self._client is not None
        system = f"{request.core.rstrip()}\n\n{request.rules}" if request.core.strip() else request.rules
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *_wire(request.messages)],
            "stream": True,
            "max_tokens": request.max_tokens,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = openai_tools(tools)
        reply = Reply()
        said: list[str] = []
        pending: dict[int, dict[str, str]] = {}
        async with self._client.stream("POST", "/chat/completions", json=body) as response:
            if tools and response.status_code in TOOLS_REFUSED:
                raise _ToolsRefused
            if response.status_code >= 400:
                raise LocalModelError(_status_error(response.status_code))
            async for line in response.aiter_lines():
                if self._halt:
                    reply.stop = "interrupted"
                    break
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                _chunk(reply, said, pending, json.loads(data), on_text)
        if tools:
            self._tools = True
        reply.text = "".join(said)
        reply.calls = [_call(p) for _, p in sorted(pending.items())]
        if reply.calls and reply.stop == "end_turn":
            reply.stop = "tool_use"
        return reply


class _ToolsRefused(Exception):
    pass


def _chunk(
    reply: Reply, said: list[str], pending: dict[int, dict[str, str]], chunk: dict[str, Any], on_text: OnText | None
) -> None:
    usage = chunk.get("usage")
    if usage:
        reply.input_tokens = int(usage.get("prompt_tokens") or 0)
        reply.output_tokens = int(usage.get("completion_tokens") or 0)
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content:
            said.append(content)
            if on_text is not None:
                on_text(content)
        for part in delta.get("tool_calls") or []:
            slot = pending.setdefault(int(part.get("index", len(pending))), {"id": "", "name": "", "arguments": ""})
            slot["id"] = part.get("id") or slot["id"]
            fn = part.get("function") or {}
            slot["name"] += fn.get("name") or ""
            slot["arguments"] += fn.get("arguments") or ""
        finish = choice.get("finish_reason")
        if finish == "length":
            reply.stop = "max_tokens"


def _call(part: dict[str, str]) -> Call:
    call_id = part["id"] or f"call_{uuid.uuid4().hex[:12]}"
    raw = f"{part['name']}({part['arguments']})"
    if not part["name"]:
        return Call(call_id, "", {}, "it names no tool", raw)
    try:
        args = json.loads(part["arguments"]) if part["arguments"].strip() else {}
    except json.JSONDecodeError as exc:
        return Call(call_id, part["name"], {}, f"its arguments are not valid JSON ({exc.msg})", raw)
    if not isinstance(args, dict):
        return Call(call_id, part["name"], {}, "its arguments are not a JSON object", raw)
    return Call(call_id, part["name"], args, "", raw)
