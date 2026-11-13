"""The standalone app: everything the daemon needs inside the bundle.

`build_standalone` stages a payload for `Contents/Resources`, then hands it to
the ordinary build:

    python/     the relocatable Python this project runs on (uv's build), with
                every locked dependency, all extras, and the `vision` package
    house/      the default house, the tool catalog and the agents' personas
    web/dist/   the built window: the house and the widget

Run-time leftovers are stripped (caches, tests, headers, entry-point scripts,
Tk, pip), fresh bytecode is compiled so nothing is ever written into the
bundle, and every Mach-O file is signed ad hoc so the whole app verifies.
User data stays in `~/.vision` and models in the Hugging Face cache.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from vision.core.config import Config
from vision.core.programs import find_program
from vision.macapp.bundle import DIST, ICON, REPO_ROOT, AppBuildError, Runner, build

PYTHON_VERSION = "3.12"
RUNTIME_PRUNE = (
    "include",
    "share",
    "bin/2to3*",
    "bin/idle3*",
    "bin/pip*",
    "bin/pydoc3*",
    "bin/python3*-config",
    "lib/pkgconfig",
    "lib/itcl*",
    "lib/thread*",
    "lib/tcl*",
    "lib/tk*",
    "lib/libtcl*",
    "lib/libtk*",
    f"lib/python{PYTHON_VERSION}/config-*",
    f"lib/python{PYTHON_VERSION}/ensurepip",
    f"lib/python{PYTHON_VERSION}/idlelib",
    f"lib/python{PYTHON_VERSION}/lib-dynload/_tkinter*",
    f"lib/python{PYTHON_VERSION}/tkinter",
    f"lib/python{PYTHON_VERSION}/turtledemo",
    f"lib/python{PYTHON_VERSION}/site-packages/pip",
    f"lib/python{PYTHON_VERSION}/site-packages/pip-*.dist-info",
)
"""Parts of the Python runtime the daemon never uses, relative to its prefix."""
SITE_PRUNE = ("PyObjCTest",)
"""Whole test packages some dependencies install beside themselves."""
PRUNE_DIRS = frozenset({"tests", "test"})
PRUNE_FILES = ("*.h", "*.hpp", "*.c", "*.cpp", "*.pyx", "*.pxd", "*.a", "direct_url.json")
"""Removed from site-packages. `direct_url.json` would name the build folder."""
KEEP_HEADERS = ("mlx",)
"""Packages whose headers are read at run time (MLX compiles Metal kernels from them)."""
WEB_PAGES = ("index.html", "widget.html")
"""The pages `npm run build` writes into `web/dist`: the house and the floating widget."""
MACHO_MAGIC = {
    bytes.fromhex(m) for m in ("cffaedfe", "cefaedfe", "feedfacf", "feedface", "cafebabe", "bebafeca")
}


def runtime_prefix() -> Path:
    """The Python install this project's `.venv` was made from: uv's relocatable build."""
    prefix = Path(sys.base_prefix)
    if not (prefix / "lib" / f"libpython{PYTHON_VERSION}.dylib").is_file():
        raise AppBuildError(
            f"{prefix} is not a relocatable Python {PYTHON_VERSION}. Create the environment "
            f"with a uv-managed Python: `uv python install {PYTHON_VERSION}` and `uv sync`."
        )
    return prefix


def bundled_python(python_dir: Path) -> Path:
    return python_dir / "bin" / f"python{PYTHON_VERSION}"


def site_packages(python_dir: Path) -> Path:
    return python_dir / "lib" / f"python{PYTHON_VERSION}" / "site-packages"


def stage(
    stage_dir: Path,
    *,
    runtime: Path,
    project: Path = REPO_ROOT,
    uv: Path,
    run: Runner = subprocess.run,
) -> Path:
    """Fill `stage_dir` with the payload; return it. Everything in it is signed."""
    web = project / "web" / "dist"
    if not all((web / page).is_file() for page in WEB_PAGES):
        raise AppBuildError(
            "The window is not built; run `cd web && npm ci && npm run build` first."
        )
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    python_dir = stage_dir / "python"
    shutil.copytree(runtime, python_dir, symlinks=True)
    remove_matching(python_dir, RUNTIME_PRUNE)
    forget_prefix(python_dir, runtime)
    install_packages(python_dir, project=project, uv=uv, run=run)
    strip_site_packages(site_packages(python_dir))
    remove_bytecode(python_dir)
    remove_scripts(python_dir / "bin")
    compile_bytecode(python_dir, run=run)
    shutil.copytree(project / "house", stage_dir / "house")
    shutil.copytree(web, stage_dir / "web" / "dist")
    sign_machos(stage_dir, run=run)
    return stage_dir


def forget_prefix(python_dir: Path, runtime: Path) -> None:
    """The build configuration names the builder's Python folder; Python works without it."""
    for path in (python_dir / "lib" / f"python{PYTHON_VERSION}").glob("_sysconfigdata_*.py"):
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(str(runtime), "/install"), encoding="utf-8")


def install_packages(python_dir: Path, *, project: Path, uv: Path, run: Runner) -> None:
    """The locked dependencies with every extra, then `vision` itself (not editable)."""
    requirements = python_dir.parent / "requirements.txt"
    python = str(bundled_python(python_dir))
    common = ["--python", python, "--break-system-packages", "--link-mode", "copy", "--no-config"]
    steps = [
        [str(uv), "export", "--frozen", "--no-dev", "--all-extras", "--no-emit-project",
         "--no-hashes", "--format", "requirements-txt", "--output-file", str(requirements)],
        [str(uv), "pip", "install", *common, "--requirement", str(requirements)],
        [str(uv), "pip", "install", *common, "--no-deps", str(project)],
    ]
    try:
        for argv in steps:
            if run(argv, cwd=project, check=False).returncode != 0:
                raise AppBuildError(f"`{' '.join(argv[:3])}` failed; its output is above.")
    finally:
        requirements.unlink(missing_ok=True)


def remove_matching(root: Path, patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        for path in root.glob(pattern):
            remove(path)


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def strip_site_packages(packages: Path) -> None:
    """Tests, headers and sources of compiled code: not needed to run."""
    remove_matching(packages, SITE_PRUNE)
    for dirpath, dirnames, filenames in os.walk(packages, topdown=True):
        here = Path(dirpath)
        top = here.relative_to(packages).parts[:1]
        keep_headers = bool(top) and top[0] in KEEP_HEADERS
        for name in [d for d in dirnames if d in PRUNE_DIRS]:
            shutil.rmtree(here / name)
            dirnames.remove(name)
        for name in filenames:
            if keep_headers and name.endswith((".h", ".hpp")):
                continue
            if any(fnmatch.fnmatch(name, p) for p in PRUNE_FILES):
                (here / name).unlink()


def remove_bytecode(root: Path) -> None:
    """Old bytecode, compiled against the build folder's paths and timestamps."""
    for cache in list(root.rglob("__pycache__")):
        shutil.rmtree(cache)


def remove_scripts(bin_dir: Path) -> None:
    """Entry-point scripts name the build folder's Python; only the interpreter stays."""
    for path in bin_dir.iterdir():
        if not path.name.startswith("python"):
            remove(path)


def compile_bytecode(python_dir: Path, *, run: Runner) -> None:
    """Hash-checked bytecode, valid wherever the app is copied, so imports never write.

    File names inside it are relative; Python sets the real ones when it imports.
    """
    argv = [str(bundled_python(python_dir)), "-I", "-W", "ignore", "-m", "compileall", "-q", "-f", "-j", "0",
            "--invalidation-mode", "unchecked-hash", "-s", str(python_dir),
            str(python_dir / "lib")]
    # Exit status 1 means some file did not compile (Python 2 leftovers in a package);
    # those are compiled in memory at import instead. Anything else is a real failure.
    if run(argv, check=False).returncode not in (0, 1):
        raise AppBuildError("Compiling the bytecode failed; its output is above.")


def machos(root: Path) -> Iterator[Path]:
    """Every Mach-O file (executable, library or extension module) under `root`."""
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            with path.open("rb") as fh:
                if fh.read(4) in MACHO_MAGIC:
                    yield path


def sign_machos(root: Path, *, run: Runner, batch: int = 200) -> int:
    """Sign each Mach-O file ad hoc; the bundle's seal then covers them. Returns how many."""
    paths = [str(p) for p in machos(root)]
    for start in range(0, len(paths), batch):
        argv = ["codesign", "--force", "--sign", "-", "--timestamp=none", *paths[start:start + batch]]
        if run(argv, check=False, capture_output=True, text=True).returncode != 0:
            raise AppBuildError("Signing the bundled libraries failed.")
    return len(paths)


def build_standalone(
    config: Config,
    *,
    project: Path = REPO_ROOT,
    dist: Path = DIST,
    icon: Path = ICON,
    run: Runner = subprocess.run,
) -> Path:
    """`dist/<name>.app` with its own Python, packages, house and window."""
    uv = find_program("uv")
    if uv is None:
        raise AppBuildError("The standalone build needs uv (`brew install uv`).")
    payload = stage(dist / ".standalone", runtime=runtime_prefix(), project=project, uv=uv, run=run)
    try:
        return build(config, project=project, dist=dist, icon=icon, payload=payload, run=run)
    finally:
        shutil.rmtree(payload, ignore_errors=True)
