"""One background thread for all model work (VAD, Whisper, Kokoro).

MLX work from several threads at once is not something to rely on, and the
models are used one at a time anyway, so they share a single worker thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")


class Worker:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision-voice")

    async def run(self, fn: Callable[[], T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._pool, fn)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
