"""Memory: the Markdown vault and the SQLite turn and audit log.

The composition root (`vision.app`) calls `make_memory`. Until it is
implemented it raises `NotImplementedError` and the daemon uses
`vision.testing.fakes.FakeMemory` (in memory only), publishing a notice.
"""

from __future__ import annotations

from vision.core.config import Config
from vision.core.interfaces import Memory


def make_memory(config: Config) -> Memory:
    """Build Vision's memory.

    Must return an object satisfying `vision.core.interfaces.Memory`, storing
    the vault under `config.paths.house` and the log at `config.paths.log_db`.
    Must not touch the disk here; do that in `Memory.start()`, which the
    daemon awaits before anything else starts.
    """
    raise NotImplementedError("vision.memory.make_memory is not implemented yet")
