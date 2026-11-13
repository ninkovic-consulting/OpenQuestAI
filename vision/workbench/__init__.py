"""The workbench: the tools an agent uses to work inside a room's project folders.

`project_tools(folders, programs)` takes the room's folders, in its order
(one to eight). Every path starts with a folder's short name
(`shop-api/src/app.py`, names from `vision.core.folders`), with one folder
as with several, so a path keeps its meaning when a folder is added; `.`
stands for all of them, and run_program takes the folder to run in (the
first by default). It returns, in this order: list_files,
read_file, search_files, write_file, edit_file, run_program. The caller sets
the tiers: the first three free, write_file and edit_file ask, run_program
always asks (a program such as git, npm or python can run any code the
project contains).

Safety rules, enforced here and not left to the model:
1. nothing outside the real folder a path is addressed through
   (paths resolved for real, links that lead out refused, never followed
   while listing or searching); a link from one of the room's folders into
   another is refused like any link out;
2. protected files (secrets, keys, credentials; see `protected.py`) are never
   read, searched or written;
3. `.git/` is never written, git hooks are never created or changed;
4. programs get a clean environment, no stdin, a timeout and an output cap;
5. only the owner's programs, by id, with checked arguments;
6. refusals say why, without file contents or paths outside the project.
"""

from vision.workbench.tools import NAMES, project_tools

__all__ = ["NAMES", "project_tools"]
