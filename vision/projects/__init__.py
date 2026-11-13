"""New projects: the host starts one for the owner and gives it to the best-suited resident.

`start_project` (the host's only, always asking first) makes a folder under
`[projects] root` with a README.md and, when git is installed, a repository;
adds a room holding it, run by the chosen resident; and hands that resident a
first job there when one is given. It can attach an existing folder instead.
Everything it will do is worked out first (`plan`) and shown on the gate
card; a yes carries out exactly that (`make`).

The composition root (`vision.app`) offers `build_tools(house, board, root)`
to the host's gate, with `saved_root(config)` as the root.
"""

from __future__ import annotations

from vision.projects.names import Refused, RootProblem, folder_name, projects_root, saved_root
from vision.projects.tools import build_tools

__all__ = ["Refused", "RootProblem", "build_tools", "folder_name", "projects_root", "saved_root"]
