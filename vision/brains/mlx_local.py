"""The local model in process (`[brain] local_backend = "mlx"`): an MLX model on Apple
Silicon, no server.

- The model (a Hugging Face repo in MLX format) is loaded when it is wanted:
  at once when offline mode is on (`preload`, which the engine calls when
  offline mode is switched on and at start-up), else on the first generation.
  A generation that comes during the load waits for it. While offline mode is
  on, or `[brain] local_keep_loaded = "always"`, it stays in memory; otherwise
  it is freed after `[brain] local_idle_unload_s` without a generation.
- What a generation has read is kept for the next one (`prompt_cache`), so a
  turn reads only the tokens its prompt does not share with an earlier one.
- `status()` says whether the model is in memory, how much memory it and the
  kept prompts hold, and how far a long prompt has been read before the first
  word; `changed` is called whenever that changes.
- Only safetensors weights, JSON configs, the tokenizer and the chat template
  are fetched, and remote code is never trusted.
- Nothing is ever downloaded here: a model is fetched only when the owner
  asks (Settings, the first-start wizard, `vision setup`, through
  `setup_model`). If the model is not on disk, the generation fails with a
  `BrainError` and a `notice` (once, until a model is there) saying that no
  local model is downloaded and where to choose one.
- Tools follow the model's own chat template, as mlx-lm reads it: the
  tokenizer names the tool-call markers and the parser for the model's family
  (`TokenizerWrapper.has_tool_calling`, `tool_parser`), and mlx-lm's
  `TextStateMachine` splits the streamed text into what is said, what is
  thought (never shown) and tool calls. A model whose template has no tool
  format is talk-only; that is read from its tokenizer, not from a list.
- All MLX work runs on one dedicated thread, off the event loop. `stop()`
  ends generation at the next token.
- The system prompt is cut short if the conversation would not fit in
  `[brain] local_context_tokens` (or the model's own context).
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vision.brains.local_chat import (
    Call,
    Message,
    OnText,
    Reply,
    Request,
    Status,
    Who,
    openai_tools,
)
from vision.brains.local_errors import LocalModelError
from vision.brains.prompt_cache import KV, PromptCaches
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import LocalLoad, Notice
from vision.core.interfaces import BrainError
from vision.setup import hf_cache

log = logging.getLogger(__name__)

PROMPT_MARGIN_TOKENS = 64
FILE_PATTERNS = ["*.json", "*.safetensors", "*.jinja", "*.txt", "tokenizer.model"]
"""What is fetched: configs, safetensors weights, tokenizer and chat template. Never code."""
TEMPERATURE = 0.7
TOP_P = 0.8
NEEDS = "*.safetensors"
"""A snapshot counts as downloaded once it has weights."""
READING_SHOWN = 512
"""A prompt with at least this many tokens to read is shown as being read (a second or more)."""

Section = tuple[str, str]
"""A piece of streamed text and what it is: `normal`, `reasoning` or `tool`."""


@dataclass(frozen=True, slots=True)
class Piece:
    """One generated token: its text (possibly empty), its id and the count so far. The token
    is already in the cache when its piece arrives."""

    text: str
    token: int
    generation_tokens: int
    finish_reason: str | None


Progress = Callable[[int, int], None]
"""Called while the prompt is read: tokens read so far and the tokens to read."""


class Splitter(Protocol):
    """Splits streamed text into sections; control markers are dropped."""

    def feed(self, text: str) -> list[Section]: ...

    def end(self, finish: str | None) -> list[Section]:
        """What is held back at the end: kept when generation was cut off, else dropped."""
        ...


class LoadedModel(Protocol):
    """A model in memory with its tokenizer."""

    context_tokens: int
    """The model's own context length."""
    tools: bool
    """The tokenizer knows the model's tool-call format."""
    weights_bytes: int
    """The memory its weights hold."""

    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: list[int]) -> str: ...

    def chat_prompt(
        self, messages: list[Message], tools: list[dict[str, Any]] | None, thinking: bool
    ) -> list[int]:
        """The chat template applied to `messages` (and the tools), ready for the reply."""
        ...

    def new_kv(self) -> KV:
        """An empty prompt cache."""
        ...

    def stream(self, prompt: list[int], max_tokens: int, kv: KV, progress: Progress) -> Iterator[Piece]:
        """Read `prompt` on top of what `kv` holds, then generate; `kv` grows in place."""
        ...

    def splitter(self) -> Splitter: ...

    def parse_calls(self, text: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The calls in one tool section, as `{"name", "arguments"}`. Raises ValueError."""
        ...


class Runtime(Protocol):
    """The parts of the MLX stack the backend uses; every call blocks."""

    def cached(self, repo: str) -> Path | None:
        """The model's folder if every needed file is already on disk, else None."""
        ...

    def download_size(self, repo: str) -> int:
        """Bytes to fetch. Raises when the hub cannot be reached."""
        ...

    def download(self, repo: str) -> Path: ...

    def load(self, path: Path) -> LoadedModel: ...

    def can_call_tools(self, path: Path) -> bool:
        """Read from the tokenizer alone, without loading the weights."""
        ...

    def release(self) -> None:
        """Return freed model memory to the system."""
        ...


# ------------------------------------------------------------ the real runtime


class _MlxSplitter:
    def __init__(self, machine: Any, initial: str) -> None:
        from mlx_lm.generate import TextStateMachine

        self._sm = TextStateMachine
        self._state = machine.make_state(initial)

    def feed(self, text: str) -> list[Section]:
        self._state, segments = self._sm.split(self._state, text)
        return [(str(s), t) for s, t in segments]

    def end(self, finish: str | None) -> list[Section]:
        if finish == "length":
            self._state, flushed, state = self._sm.flush(self._state)
            return [(str(state), flushed)]
        self._state, state = self._sm.discard(self._state)
        return [(str(state), "")]


class _MlxKV:
    """mlx-lm's prompt cache: one cache per layer (`make_prompt_cache`)."""

    def __init__(self, layers: list[Any]) -> None:
        self.layers = layers

    def trimmable(self) -> bool:
        from mlx_lm.models.cache import can_trim_prompt_cache

        return bool(can_trim_prompt_cache(self.layers))

    def trim(self, n: int) -> None:
        from mlx_lm.models.cache import trim_prompt_cache

        trim_prompt_cache(self.layers, n)

    def nbytes(self) -> int:
        return sum(int(c.nbytes) for c in self.layers)

    def size(self) -> int | None:
        """The attention layers' length; layers that keep no positions (linear attention) say 0."""
        return max((int(c.size()) for c in self.layers), default=0) or None


class _MlxModel:
    def __init__(self, model: Any, tokenizer: Any, context_tokens: int, weights_bytes: int) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.context_tokens = context_tokens
        self.weights_bytes = weights_bytes
        self.tools = bool(tokenizer.has_tool_calling)
        self._last_prompt: list[int] = []

    def encode(self, text: str) -> list[int]:
        return list(self._tokenizer.encode(text, add_special_tokens=False))

    def decode(self, tokens: list[int]) -> str:
        return str(self._tokenizer.decode(tokens))

    def chat_prompt(
        self, messages: list[Message], tools: list[dict[str, Any]] | None, thinking: bool
    ) -> list[int]:
        text = self._tokenizer.apply_chat_template(
            messages,
            tools=tools or None,
            add_generation_prompt=True,
            tokenize=False,
            enable_thinking=thinking,
        )
        self._last_prompt = self.encode(text)
        return self._last_prompt

    def new_kv(self) -> KV:
        from mlx_lm.models.cache import make_prompt_cache

        return _MlxKV(make_prompt_cache(self._model))

    def stream(self, prompt: list[int], max_tokens: int, kv: KV, progress: Progress) -> Iterator[Piece]:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        assert isinstance(kv, _MlxKV)
        sampler = make_sampler(temp=TEMPERATURE, top_p=TOP_P)
        for r in stream_generate(
            self._model,
            self._tokenizer,
            prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            prompt_cache=kv.layers,
            prompt_progress_callback=progress,
        ):
            yield Piece(r.text, r.token, r.generation_tokens, r.finish_reason)

    def splitter(self) -> Splitter:
        from mlx_lm.generate import make_text_state_machine

        tok = self._tokenizer
        initial = "normal"
        if tok.has_thinking and tok.rfind_think_start(self._last_prompt) > tok.rfind_think_end(
            self._last_prompt
        ):
            initial = "reasoning"  # the template opened the thinking block itself
        initial = tok.response_initial_state or initial
        return _MlxSplitter(make_text_state_machine(tok), initial)

    def parse_calls(self, text: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parser = self._tokenizer.tool_parser
        if parser is None:
            raise ValueError("this model has no tool-call format")
        try:
            parsed = parser(text, tools)
        except json.JSONDecodeError as exc:
            raise ValueError(f"the arguments are not valid JSON ({exc.msg})") from None
        return parsed if isinstance(parsed, list) else [parsed]


class MlxRuntime:
    """mlx-lm and huggingface_hub, imported only when first needed."""

    def cached(self, repo: str) -> Path | None:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        try:
            path = Path(
                snapshot_download(
                    repo,
                    allow_patterns=FILE_PATTERNS,
                    local_files_only=True,
                    cache_dir=hf_cache.hub_cache(),
                )
            )
        except LocalEntryNotFoundError:
            return None
        return path if any(path.glob("*.safetensors")) else None

    def download_size(self, repo: str) -> int:
        from fnmatch import fnmatch

        from huggingface_hub import HfApi

        info = HfApi().model_info(repo, files_metadata=True)
        return sum(
            s.size or 0
            for s in info.siblings or []
            if any(fnmatch(s.rfilename, p) for p in FILE_PATTERNS)
        )

    def download(self, repo: str) -> Path:
        from huggingface_hub import snapshot_download

        return Path(
            snapshot_download(repo, allow_patterns=FILE_PATTERNS, cache_dir=hf_cache.hub_cache())
        )

    def load(self, path: Path) -> LoadedModel:
        from mlx.utils import tree_flatten
        from mlx_lm import load

        model, tokenizer = load(str(path), trust_remote_code=False)
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        text_config = config.get("text_config") or {}
        key = "max_position_embeddings"
        context = config.get(key) or text_config.get(key)
        weights = sum(int(v.nbytes) for _, v in tree_flatten(model.parameters()))
        return _MlxModel(model, tokenizer, int(context or 4096), weights)

    def can_call_tools(self, path: Path) -> bool:
        from mlx_lm.utils import load_tokenizer

        return bool(load_tokenizer(path).has_tool_calling)

    def release(self) -> None:
        import mlx.core as mx

        gc.collect()
        mx.clear_cache()


def setup_model(repo: str, runtime: Runtime | None = None) -> tuple[Path, int | None]:
    """Download `repo` if needed. Returns its folder and the bytes fetched."""
    rt = runtime or MlxRuntime()
    path = rt.cached(repo)
    if path is not None:
        return path, None
    size = rt.download_size(repo)
    return rt.download(repo), size


# ------------------------------------------------------------ the backend


def not_downloaded(repo: str) -> str:
    return (
        f"No local model is downloaded on this Mac ({repo} is not here), so nothing can answer "
        "on the local model. Choose one and download it in Settings, under Models; nothing is "
        "downloaded by itself."
    )


def cannot_load(repo: str, exc: Exception) -> str:
    return (
        f"The local model {repo} could not be loaded ({type(exc).__name__}). Choose another in "
        "Settings, under Models, or turn offline mode off to answer on Claude."
    )


def missing_extra() -> BrainError:
    return BrainError(
        "unavailable",
        "The in-process local model needs Apple Silicon and `uv sync --extra local`.",
        False,
    )


class MlxBackend:
    """One MLX model, loaded when wanted. The engine calls it one generation at a time."""

    def __init__(
        self, config: Config, bus: Bus, repo: str, *, runtime: Runtime | None = None
    ) -> None:
        self._config = config
        self._bus = bus
        self.model = repo
        self.changed: Callable[[], None] = lambda: None
        """Called on the event loop whenever `status()` changes."""
        self._runtime: Runtime = runtime or MlxRuntime()
        self._executor: ThreadPoolExecutor | None = None
        self._loaded: LoadedModel | None = None
        self._lock = asyncio.Lock()
        self._halt = threading.Event()
        self._idle: asyncio.TimerHandle | None = None
        self._unloading: asyncio.Task[None] | None = None
        self._tools: bool | None = None
        self._told = False
        self._caches = PromptCaches()
        """Only touched on the MLX thread."""
        self._state: LocalLoad = "unloaded"
        self._problem: str | None = None
        self._reading: tuple[int, int] | None = None
        self._cache_bytes = 0
        self._generating = 0

    @property
    def loaded(self) -> bool:
        return self._loaded is not None

    @property
    def known_tools(self) -> bool | None:
        """Whether the model can call tools, once read; None before."""
        return self._tools

    def status(self) -> Status:
        weights = self._loaded.weights_bytes if self._loaded is not None else None
        return Status(self._state, weights, self._cache_bytes, self._reading, self._problem)

    async def start(self) -> None:
        """Nothing is loaded here; `preload` or the first generation loads the model."""
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")

    def stop(self) -> None:
        self._halt.set()

    async def close(self) -> None:
        self._halt.set()
        self._cancel_idle()
        await self._unload()
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    async def ready(self) -> str | None:
        """Why the model cannot answer offline now, or None. Reads the disk only."""
        size = await asyncio.to_thread(hf_cache.cached_size, self.model, needs=NEEDS)
        return not_downloaded(self.model) if size is None else None

    async def can_call_tools(self) -> bool:
        """Read once per model from its tokenizer (or the loaded model)."""
        if self._tools is None:
            if self._loaded is not None:
                self._tools = self._loaded.tools
            else:
                path = await self._call(self._runtime.cached, self.model)
                if path is None:
                    return False
                self._tools = bool(await self._call(self._runtime.can_call_tools, path))
        return self._tools

    async def preload(self) -> None:
        """Load the model now, if it is not in memory. A failure is in `status()` and said once
        as a notice; the next generation tries again."""
        try:
            await self._ensure_model()
        except LocalModelError:
            pass
        self.follow_policy()

    def follow_policy(self) -> None:
        """Keep the model in memory or let it go when idle, as the settings say now."""
        if self._loaded is not None and self._generating == 0:
            self._arm_idle()

    async def generate(self, request: Request, on_text: OnText | None, who: Who = "host") -> Reply:
        self._cancel_idle()
        self._generating += 1
        try:
            model = await self._ensure_model()
            self._halt.clear()
            tools = openai_tools(request.tools) if model.tools and request.tools else []
            prompt = await self._call(self._prompt, model, request, tools)
            loop = asyncio.get_running_loop()

            def push(text: str) -> None:
                if on_text is not None:
                    loop.call_soon_threadsafe(on_text, text)

            def progress(done: int, total: int) -> None:
                if total >= READING_SHOWN:
                    loop.call_soon_threadsafe(self._read, done, total)

            reply, self._cache_bytes = await self._call(
                self._generate, model, prompt, request, tools, push, progress, who
            )
            return reply
        finally:
            self._generating -= 1
            self._reading = None
            self.changed()
            self._arm_idle()

    # ------------------------------------------------------------ loading

    async def _call(self, fn: Any, *args: Any) -> Any:
        if self._executor is None:
            raise LocalModelError(BrainError("internal", "The local brain was not started.", False))
        try:
            return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)
        except ImportError as exc:
            raise LocalModelError(missing_extra()) from exc

    async def _ensure_model(self) -> LoadedModel:
        async with self._lock:
            if self._loaded is not None:
                return self._loaded
            repo = self.model
            try:
                path = await self._call(self._runtime.cached, repo)
                if path is None:
                    raise self._not_here()
                self._set("loading", None)
                try:
                    loaded: LoadedModel = await self._call(self._runtime.load, path)
                except LocalModelError:
                    raise
                except Exception as exc:
                    log.exception("loading the local model failed")
                    raise LocalModelError(
                        BrainError("unavailable", cannot_load(repo, exc), False)
                    ) from exc
            except LocalModelError as exc:
                self._fail(exc.error.message)
                raise
            self._loaded = loaded
            self._tools = loaded.tools
            self._told = False
            self._set("ready", None)
            log.info("local model %s loaded (%d MB)", repo, loaded.weights_bytes // 2**20)
            return loaded

    def _not_here(self) -> LocalModelError:
        """No model on disk: fail the generation. Fetch nothing."""
        return LocalModelError(BrainError("unavailable", not_downloaded(self.model), False))

    def _fail(self, message: str) -> None:
        """Say a failed load once as a notice (until a load works), and show it."""
        if not self._told:
            self._told = True
            self._bus.publish(Notice(level="warn", text=message))
        self._set("failed", message)

    def _set(self, state: LocalLoad, problem: str | None) -> None:
        self._state, self._problem = state, problem
        self.changed()

    def _read(self, done: int, total: int) -> None:
        self._reading = (done, total) if done < total and self._generating else None
        self.changed()

    async def _unload(self) -> None:
        async with self._lock:
            if self._loaded is None:
                return
            self._loaded = None
            if self._executor is not None:
                await self._call(self._drop)
            self._cache_bytes = 0
            self._set("unloaded", None)
            log.info("local model unloaded")

    def _drop(self) -> None:
        self._caches.clear()
        self._runtime.release()

    def _keep(self) -> bool:
        brain = self._config.brain
        return brain.offline or brain.local_keep_loaded == "always"

    def _arm_idle(self) -> None:
        self._cancel_idle()
        if self._keep():
            return
        loop = asyncio.get_running_loop()
        self._idle = loop.call_later(self._config.brain.local_idle_unload_s, self._on_idle)

    def _cancel_idle(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None

    def _on_idle(self) -> None:
        self._idle = None
        if self._generating or self._keep():
            return
        self._unloading = asyncio.get_running_loop().create_task(self._unload())

    # ------------------------------------------------------------ one generation

    def _prompt(self, model: LoadedModel, request: Request, tools: list[dict[str, Any]]) -> list[int]:
        """The chat prompt, with the core cut short if the whole would not fit."""
        brain = self._config.brain
        window = min(model.context_tokens, brain.local_context_tokens)
        bare = model.chat_prompt(
            [{"role": "system", "content": request.rules}, *request.messages], tools, request.thinking
        )
        room = window - request.max_tokens - len(bare) - PROMPT_MARGIN_TOKENS
        core = request.core
        tokens = model.encode(core)
        if len(tokens) > room:
            core = model.decode(tokens[: max(room, 0)])
        system = f"{core.rstrip()}\n\n{request.rules}" if core.strip() else request.rules
        return model.chat_prompt(
            [{"role": "system", "content": system}, *request.messages], tools, request.thinking
        )

    def _generate(
        self,
        model: LoadedModel,
        prompt: list[int],
        request: Request,
        tools: list[dict[str, Any]],
        push: Callable[[str], None],
        progress: Progress,
        who: Who,
    ) -> tuple[Reply, int]:
        """One generation on the MLX thread, reading only what the kept prompts lack. Answers
        the reply and the memory the kept prompts hold after it."""
        reply = Reply(input_tokens=len(prompt))
        said: list[str] = []
        raw: list[str] = []
        calls: list[str] = []
        splitter = model.splitter()
        state = "normal"
        finish: str | None = None

        def take(sections: list[Section]) -> None:
            nonlocal state
            for section, text in sections:
                if state == "tool" and section != "tool":
                    calls.append("".join(raw))
                    raw.clear()
                state = section
                if section == "tool":
                    raw.append(text)
                elif section == "normal" and text:
                    said.append(text)
                    push(text)

        kv, known = self._caches.take(prompt, model.new_kv)
        log.info("local %s turn: %d prompt tokens, %d already read", who, len(prompt), known)
        held = list(prompt)
        with closing(model.stream(prompt[known:], request.max_tokens, kv, progress)) as pieces:
            for piece in pieces:
                held.append(piece.token)  # the cache has it already
                if self._halt.is_set():
                    reply.stop = "interrupted"
                    break
                take(splitter.feed(piece.text))
                reply.output_tokens = piece.generation_tokens
                finish = piece.finish_reason
                if finish:
                    break
        self._caches.keep(held, kv, who)
        if reply.stop != "interrupted":
            take(splitter.end(finish))
            if state == "tool" and raw:
                calls.append("".join(raw))  # a format with no end marker, or cut off
            if finish == "length":
                reply.stop = "max_tokens"
        reply.text = "".join(said)
        reply.calls = [c for text in calls for c in _calls(model, text, tools)]
        if reply.calls and reply.stop == "end_turn":
            reply.stop = "tool_use"
        return reply, self._caches.nbytes


def _calls(model: LoadedModel, text: str, tools: list[dict[str, Any]]) -> list[Call]:
    """The calls in one tool section; one that cannot be read becomes a call with a problem."""
    try:
        parsed = model.parse_calls(text, tools)
    except Exception as exc:
        return [Call(_id(), "", {}, f"it could not be read ({exc})", text.strip())]
    out: list[Call] = []
    for item in parsed:
        name = item.get("name") if isinstance(item, dict) else None
        args = item.get("arguments", {}) if isinstance(item, dict) else None
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = None
        if not isinstance(name, str) or not name:
            out.append(Call(_id(), "", {}, "it names no tool", text.strip()))
        elif not isinstance(args, dict):
            out.append(Call(_id(), name, {}, "its arguments are not a JSON object", text.strip()))
        else:
            out.append(Call(_id(), name, args, "", text.strip()))
    return out


def _id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"
