"""The local brain in process (`[brain] local_backend = "mlx"`): an MLX model on
Apple Silicon, no server, no tools.

- The model (`[brain] local_model`, a Hugging Face repo in MLX format) is
  loaded on the first local turn, never at start-up, and freed again after
  `[brain] local_idle_unload_s` without a local turn.
- Only safetensors weights, JSON configs and the tokenizer are fetched, and
  remote code is never trusted.
- If the model is not on disk yet, the first local turn downloads it after a
  `notice` that says so and how big it is. If it cannot be fetched (offline),
  the turn fails with a `BrainError` that says to run `vision setup` online.
- All MLX work runs on one dedicated thread, off the event loop. `interrupt()`
  ends the stream at once and stops generation at the next token.
- The system prompt is `memory.core()`, cut short if the conversation would
  not fit in `[brain] local_context_tokens` (or the model's own context).
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vision.brains.local import LocalModelError
from vision.brains.pump import Emit, Pump
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BrainName, Notice
from vision.core.interfaces import BrainError, BrainEvent, Memory, TextDelta, TurnDone

log = logging.getLogger(__name__)

DEFAULT_HISTORY_TURNS = 20
PROMPT_MARGIN_TOKENS = 64
FILE_PATTERNS = ["*.json", "*.safetensors", "*.jinja", "*.txt", "tokenizer.model"]
"""What is fetched: configs, safetensors weights, tokenizer and chat template. Never code."""
TEMPERATURE = 0.7
TOP_P = 0.8

Message = dict[str, str]


@dataclass(frozen=True, slots=True)
class Piece:
    """One step of generation: new text (possibly empty) and the counts so far."""

    text: str
    prompt_tokens: int
    generation_tokens: int
    finish_reason: str | None


class LoadedModel(Protocol):
    """A model in memory with its tokenizer."""

    context_tokens: int
    """The model's own context length."""

    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: list[int]) -> str: ...

    def chat_prompt(self, messages: list[Message]) -> list[int]:
        """The chat template applied to `messages`, ready for the assistant's reply."""
        ...

    def stream(self, prompt: list[int], max_tokens: int) -> Iterator[Piece]: ...


class Runtime(Protocol):
    """The parts of the MLX stack the brain uses; every call blocks."""

    def cached(self, repo: str) -> Path | None:
        """The model's folder if every needed file is already on disk, else None."""
        ...

    def download_size(self, repo: str) -> int:
        """Bytes to fetch. Raises when the hub cannot be reached."""
        ...

    def download(self, repo: str) -> Path: ...

    def load(self, path: Path) -> LoadedModel: ...

    def release(self) -> None:
        """Return freed model memory to the system."""
        ...


# ------------------------------------------------------------ the real runtime


class _MlxModel:
    def __init__(self, model: Any, tokenizer: Any, context_tokens: int) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.context_tokens = context_tokens

    def encode(self, text: str) -> list[int]:
        return list(self._tokenizer.encode(text, add_special_tokens=False))

    def decode(self, tokens: list[int]) -> str:
        return str(self._tokenizer.decode(tokens))

    def chat_prompt(self, messages: list[Message]) -> list[int]:
        text = self._tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )
        return self.encode(text)

    def stream(self, prompt: list[int], max_tokens: int) -> Iterator[Piece]:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        sampler = make_sampler(temp=TEMPERATURE, top_p=TOP_P)
        for r in stream_generate(
            self._model, self._tokenizer, prompt, max_tokens=max_tokens, sampler=sampler
        ):
            yield Piece(r.text, r.prompt_tokens, r.generation_tokens, r.finish_reason)


class MlxRuntime:
    """mlx-lm and huggingface_hub, imported only when first needed."""

    def cached(self, repo: str) -> Path | None:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        try:
            path = Path(
                snapshot_download(repo, allow_patterns=FILE_PATTERNS, local_files_only=True)
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

        return Path(snapshot_download(repo, allow_patterns=FILE_PATTERNS))

    def load(self, path: Path) -> LoadedModel:
        from mlx_lm import load

        model, tokenizer = load(str(path), trust_remote_code=False)
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        text_config = config.get("text_config") or {}
        key = "max_position_embeddings"
        context = config.get(key) or text_config.get(key)
        return _MlxModel(model, tokenizer, int(context or 4096))

    def release(self) -> None:
        import mlx.core as mx

        gc.collect()
        mx.clear_cache()


def setup_model(config: Config, runtime: Runtime | None = None) -> tuple[Path, int | None]:
    """Download the configured local model if needed. Returns its folder and the bytes fetched."""
    rt = runtime or MlxRuntime()
    repo = config.brain.local_model
    path = rt.cached(repo)
    if path is not None:
        return path, None
    size = rt.download_size(repo)
    return rt.download(repo), size


# ------------------------------------------------------------ the brain


def _gigabytes(size: int) -> str:
    return f"{size / 1e9:.1f} GB"


@dataclass
class _Turn:
    user: Message
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class MlxBrain:
    def __init__(
        self, config: Config, bus: Bus, memory: Memory, *, runtime: Runtime | None = None
    ) -> None:
        self._config = config
        self._bus = bus
        self._memory = memory
        self._runtime: Runtime = runtime or MlxRuntime()
        extra = config.brain.model_extra or {}
        self._max_turns = max(1, int(extra.get("history_turns", DEFAULT_HISTORY_TURNS)))
        self._idle_s = config.brain.local_idle_unload_s
        self._history: list[tuple[Message, Message]] = []
        self._pump = Pump()
        self._executor: ThreadPoolExecutor | None = None
        self._model: LoadedModel | None = None
        self._lock = asyncio.Lock()
        self._halt = threading.Event()
        self._idle: asyncio.TimerHandle | None = None
        self._unloading: asyncio.Task[None] | None = None

    @property
    def name(self) -> BrainName:
        return "local"

    @property
    def model(self) -> str:
        return self._config.brain.local_model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    async def start(self) -> None:
        """Nothing is loaded here; the first local turn loads the model."""
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")

    async def interrupt(self) -> None:
        self._halt.set()
        self._pump.stop()

    async def close(self) -> None:
        self._halt.set()
        self._cancel_idle()
        await self._unload()
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    async def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        turn = _Turn(user={"role": "user", "content": text})
        error: BrainError | None = None
        said: list[str] = []
        self._cancel_idle()
        try:
            async with aclosing(self._pump.run(lambda emit: self._produce(turn, emit))) as events:
                async for event in events:
                    if isinstance(event, TextDelta):
                        said.append(event.text)
                    yield event
        except LocalModelError as exc:
            error = exc.error
        finally:
            self._halt.set()
            if error is None:
                self._commit(turn.user, "".join(said).strip())
            self._arm_idle()
        if error is not None:
            yield error
            return
        stop = "interrupted" if self._pump.interrupted else turn.stop_reason
        yield TurnDone(self.model, turn.input_tokens, turn.output_tokens, stop)

    # ------------------------------------------------------------ loading

    async def _call(self, fn: Any, *args: Any) -> Any:
        if self._executor is None:
            raise LocalModelError(BrainError("internal", "The local brain was not started.", False))
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)

    async def _ensure_model(self) -> LoadedModel:
        async with self._lock:
            if self._model is not None:
                return self._model
            repo = self.model
            try:
                path = await self._call(self._runtime.cached, repo)
            except ImportError as exc:
                raise LocalModelError(_missing_extra()) from exc
            if path is None:
                path = await self._fetch(repo)
            try:
                self._model = await self._call(self._runtime.load, path)
            except ImportError as exc:
                raise LocalModelError(_missing_extra()) from exc
            except Exception as exc:
                log.exception("loading the local model failed")
                raise LocalModelError(
                    BrainError(
                        "unavailable",
                        f"The local model {repo} could not be loaded ({type(exc).__name__}).",
                        False,
                    )
                ) from exc
            return self._model

    async def _fetch(self, repo: str) -> Path:
        not_here = (
            f"The local model {repo} is not downloaded yet and cannot be fetched now. "
            "Run `vision setup` while online to download it."
        )
        try:
            size = await self._call(self._runtime.download_size, repo)
        except Exception as exc:
            log.warning("cannot size the local model: %s", type(exc).__name__)
            raise LocalModelError(BrainError("unavailable", not_here, False)) from exc
        self._bus.publish(
            Notice(
                level="info",
                text=(
                    f"Downloading the local model {repo} ({_gigabytes(size)}). "
                    "The local answer starts when it is done."
                ),
            )
        )
        try:
            path: Path = await self._call(self._runtime.download, repo)
        except Exception as exc:
            log.warning("downloading the local model failed: %s", type(exc).__name__)
            raise LocalModelError(BrainError("unavailable", not_here, False)) from exc
        return path

    async def _unload(self) -> None:
        async with self._lock:
            if self._model is None:
                return
            self._model = None
            if self._executor is not None:
                await self._call(self._runtime.release)
            log.info("local model unloaded")

    def _arm_idle(self) -> None:
        self._cancel_idle()
        loop = asyncio.get_running_loop()
        self._idle = loop.call_later(self._idle_s, self._on_idle)

    def _cancel_idle(self) -> None:
        if self._idle is not None:
            self._idle.cancel()
            self._idle = None

    def _on_idle(self) -> None:
        self._idle = None
        self._unloading = asyncio.get_running_loop().create_task(self._unload())

    # ------------------------------------------------------------ one turn

    async def _produce(self, turn: _Turn, emit: Emit) -> None:
        model = await self._ensure_model()
        self._halt.clear()
        prompt = await self._call(self._prompt, model, self._memory.core(), turn.user)
        loop = asyncio.get_running_loop()

        def push(text: str) -> None:
            loop.call_soon_threadsafe(emit, TextDelta(text))

        await self._call(self._generate, model, prompt, turn, push)

    def _prompt(self, model: LoadedModel, core: str, user: Message) -> list[int]:
        """The chat prompt, with the memory core cut short if the whole would not fit."""
        conversation: list[Message] = []
        for past_user, reply in self._history:
            conversation += [past_user, reply]
        conversation.append(user)
        if not core:
            return model.chat_prompt(conversation)
        window = min(model.context_tokens, self._config.brain.local_context_tokens)
        room = (
            window
            - self._config.brain.max_output_tokens
            - len(model.chat_prompt(conversation))
            - PROMPT_MARGIN_TOKENS
        )
        tokens = model.encode(core)
        if len(tokens) > room:
            core = model.decode(tokens[: max(room, 0)])
        system = [{"role": "system", "content": core}] if core.strip() else []
        return model.chat_prompt(system + conversation)

    def _generate(
        self, model: LoadedModel, prompt: list[int], turn: _Turn, push: Callable[[str], None]
    ) -> None:
        for piece in model.stream(prompt, self._config.brain.max_output_tokens):
            if self._halt.is_set():
                return
            if piece.text:
                push(piece.text)
            turn.input_tokens = piece.prompt_tokens
            turn.output_tokens = piece.generation_tokens
            if piece.finish_reason:
                turn.stop_reason = "end_turn" if piece.finish_reason == "stop" else "max_tokens"

    def _commit(self, user: Message, said: str) -> None:
        if not said:
            return
        self._history.append((user, {"role": "assistant", "content": said}))
        del self._history[: -self._max_turns]


def _missing_extra() -> BrainError:
    return BrainError(
        "unavailable",
        "The in-process local model needs Apple Silicon and `uv sync --extra local`.",
        False,
    )
