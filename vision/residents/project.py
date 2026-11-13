"""The one place that imports the workbench's project tools.

`vision.workbench.project_tools(root, programs)` gives the tools that work in
a room's project folder (`list_files`, `read_file`, `search_files`,
`write_file`, `edit_file`, `run_program`). The residents receive it as an
injected `ProjectTools`, so their tests use a fake. When the package is not
installed, residents work without project tools and say so.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from vision.gate.tools import Tool

ProjectTools = Callable[[Path, Mapping[str, Path]], list[Tool]]


def load_project_tools() -> ProjectTools | None:
    try:
        from vision.workbench import project_tools
    except ImportError:
        return None
    return project_tools
