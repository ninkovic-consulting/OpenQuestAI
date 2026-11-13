"""The workbench: the tools an agent uses to work inside ONE project folder.

`project_tools(root, programs)` returns, in this order: list_files,
read_file, search_files, write_file, edit_file, run_program. The caller sets
the tiers: the first three free, write_file and edit_file ask, run_program
always asks (a program such as git, npm or python can run any code the
project contains).

Safety rules, enforced here and not left to the model:
1. nothing outside the real project folder (paths resolved for real, links
   that lead out refused, never followed while listing or searching);
2. protected files (secrets, keys, credentials; see `protected.py`) are never
   read, searched or written;
3. `.git/` is never written, git hooks are never created or changed;
4. programs get a clean environment, no stdin, a timeout and an output cap;
5. only the owner's programs, by id, with checked arguments;
6. refusals say why, without file contents or paths outside the project.
"""

from vision.workbench.tools import NAMES, project_tools

__all__ = ["NAMES", "project_tools"]
