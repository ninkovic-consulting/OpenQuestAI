"""Telling the owner: each finished top-level job becomes a turn of the host's own.

The board calls the reporter with every job the host or the owner started
once it ends. The reporter queues it and, one at a time, waits until the
assistant is idle and nobody is speaking (the same wait the automations and
the phone use), then runs a session turn with source `job` whose text says
which agent finished which job and how. The host answers in its own words;
the reply is spoken only when `[jobs] speak_results` is on and voice runs,
and is handed to the phone with the job, which decides by the owner's choice
for job results and whether the job came from the phone (`vision.remote`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from vision.core.interfaces import TurnRecord
from vision.jobs.model import Job
from vision.jobs.words import Name, report

log = logging.getLogger(__name__)

IDLE_POLL_S = 0.25

RunTurn = Callable[[str, bool], Awaitable[TurnRecord]]
"""Runs a job turn (text, speak) and returns its record; raises `RuntimeError` when busy."""
ToPhone = Callable[[Job, TurnRecord], Awaitable[None]]
"""Offers the report's turn to the phone, which sends it or not."""


class Reporter:
    def __init__(
        self,
        *,
        busy: Callable[[], bool],
        run_turn: RunTurn,
        speak: Callable[[], bool],
        to_phone: ToPhone,
        name: Name,
        poll_s: float = IDLE_POLL_S,
    ) -> None:
        self._busy = busy
        self._run_turn = run_turn
        self._speak = speak
        self._to_phone = to_phone
        self._name = name
        self._poll_s = poll_s
        self._queue: asyncio.Queue[Job] = asyncio.Queue()

    def __call__(self, job: Job) -> None:
        """The board's listener: queue a job that ended."""
        self._queue.put_nowait(job)

    async def run(self) -> None:
        """Report jobs one at a time until cancelled."""
        while True:
            job = await self._queue.get()
            try:
                await self._report(job)
            except Exception:
                log.exception("could not report job %s", job.id)

    async def _report(self, job: Job) -> None:
        text = report(job, self._name)
        while True:
            while self._busy():
                await asyncio.sleep(self._poll_s)
            try:
                record = await self._run_turn(text, self._speak())
            except RuntimeError:  # another turn slipped in first
                await asyncio.sleep(self._poll_s)
                continue
            break
        if record.reply.strip():
            await self._to_phone(job, record)
