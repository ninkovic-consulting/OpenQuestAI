"""The job board: the house at work.

The host hands work to a resident with `hand_off`; the board (`Board`)
checks it, queues it, runs it as the resident's own session (the `Work`
injected by the composition root, `vision.residents` in the daemon) within
the `[jobs]` limits, keeps it in `$VISION_HOME/jobs.json`, and announces
every change on the bus. Residents ask each other for help only through the
board, as child jobs. When a job the host or the owner started ends, the
`Reporter` gives the host a turn of its own (source `job`) to tell the owner.

The composition root (`vision.app`) builds the `Board`, offers
`build_tools(board)` to the host's gate, mounts `build_router(board)` under
`/api`, and starts the board with the residents' work once the session runs.
"""

from __future__ import annotations

from vision.jobs.board import MAX_ASKS, Board, Desk, JobError, NotFound, Outcome, Work
from vision.jobs.model import Job, Step
from vision.jobs.reports import Reporter
from vision.jobs.routes import build_router
from vision.jobs.tools import build_tools

__all__ = [
    "MAX_ASKS",
    "Board",
    "Desk",
    "Job",
    "JobError",
    "NotFound",
    "Outcome",
    "Reporter",
    "Step",
    "Work",
    "build_router",
    "build_tools",
]
