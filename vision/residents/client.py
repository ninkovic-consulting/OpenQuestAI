"""The residents' SDK client: one for all their jobs, made when the first job needs it.

The key is found the way the host's brain finds it (`vision.core.secrets`),
and a key stored later is picked up by the next job. The SDK's own retries
are off, as for the host: the worker retries a passing failure once.
"""

from __future__ import annotations

import asyncio
from typing import Any

from vision.brains.claude import default_client
from vision.core.config import Config
from vision.core.secrets import get_api_key

MIN_TIMEOUT_S = 120.0
"""A resident's call may think for a while before the first byte arrives."""


class ResidentClient:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def __call__(self) -> Any | None:
        async with self._lock:
            if self._client is None:
                key = await asyncio.to_thread(get_api_key)
                if key:
                    timeout = max(self._config.brain.request_timeout_s, MIN_TIMEOUT_S)
                    self._client = default_client(key, timeout)
            return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
