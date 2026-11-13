"""Memory: the Markdown vault, the owner's profile and library, and the SQLite log.

Settings (all optional, under `[paths]` in `config.toml`):

- `persona`: path of the persona file, relative to the home directory. Without
  it the persona is `house/agents/host.md`, then the bundled starter.
- `core_budget_chars`: size limit of `Memory.core()` (default 12000).

Beside the `Memory` protocol this package gives the owner's profile
(`profile`, `house/owner.md`), the library of documents (`documents`,
`house/library/`), their tools (`build_tools` for the host, `resident_tools`
for a resident at work), the words residents get about both
(`resident_knowledge`) and the lines the session adds about the owner
(`surroundings_line`). The library's routes are `vision.memory.routes`, mounted
by the settings routes: they need the core's token check, and the core imports
this package, so they are not imported here.
"""

from __future__ import annotations

from vision.core.config import Config
from vision.core.interfaces import Memory
from vision.memory.documents import Library
from vision.memory.service import VaultMemory
from vision.memory.shared import resident_knowledge, surroundings_line
from vision.memory.tools import build_tools, resident_tools

__all__ = [
    "Library",
    "build_tools",
    "make_memory",
    "resident_knowledge",
    "resident_tools",
    "surroundings_line",
]


def make_memory(config: Config) -> Memory:
    """Build Vision's memory. Does no I/O; `Memory.start()` creates the vault and opens the log."""
    return VaultMemory(config)
