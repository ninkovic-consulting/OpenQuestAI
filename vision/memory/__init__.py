"""Memory: the Markdown vault and the SQLite turn and audit log.

Settings (all optional, under `[paths]` in `config.toml`):

- `persona`: path of the persona file, relative to the home directory. Without
  it the persona is `house/agents/host.md`, then the bundled starter.
- `core_budget_chars`: size limit of `Memory.core()` (default 12000).
"""

from __future__ import annotations

from vision.core.config import Config
from vision.core.interfaces import Memory
from vision.memory.service import VaultMemory


def make_memory(config: Config) -> Memory:
    """Build Vision's memory. Does no I/O; `Memory.start()` creates the vault and opens the log."""
    return VaultMemory(config)
