"""The local models worth offering (`house/local_models.toml`), marked against this Mac.

The file holds what was true on Hugging Face the day it was written (the
`taken` date): sizes, parameters, context, licence and whether the chat
template can call tools. At run time each entry is marked `comfortable`,
`tight` or `too_big` for this Mac's memory, and one is recommended: the last
entry in file order (the file runs from small to large) that fits
comfortably and can use tools, else the last that fits comfortably. A model
that can use tools comes first because offline mode is only useful with them.
"""

from __future__ import annotations

import datetime as dt
import os
import tomllib
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from vision.core import resources

CATALOG_FILE = resources.house_dir() / "local_models.toml"
Fit = Literal["comfortable", "tight", "too_big"]
GIB = 1024**3
GPU_SHARE = 0.75
"""The part of memory macOS lets the GPU wire by default on Apple Silicon (larger Macs)."""
TIGHT_EXTRA_BYTES = 1_000_000_000
"""Room beyond the weights that a tight fit still needs: a short context and the runtime."""
SMALL_BYTES = 4_000_000_000
"""Models smaller than this on disk are offered the short tool list (`local_rules`)."""
KINDS = ("general", "code")
_FIELDS = {
    "id": str,
    "title": str,
    "good_at": str,
    "kind": str,
    "params_b": float,
    "size_bytes": int,
    "memory_gb": int,
    "context": int,
    "tools": bool,
    "tools_recommended": bool,
    "license": str,
}


class CatalogError(ValueError):
    """The catalog file breaks a rule; the message names the entry."""


@dataclass(frozen=True, slots=True)
class LocalModel:
    id: str
    title: str
    good_at: str
    kind: str
    params_b: float
    size_bytes: int
    memory_gb: int
    context: int
    tools: bool
    tools_recommended: bool
    license: str


@dataclass(frozen=True, slots=True)
class Catalog:
    taken: str
    models: tuple[LocalModel, ...]

    def get(self, repo: str) -> LocalModel | None:
        return next((m for m in self.models if m.id == repo), None)


@cache
def load_catalog(path: Path = CATALOG_FILE) -> Catalog:
    """The catalog in file order. Raises `CatalogError` when an entry is malformed."""
    with path.open("rb") as fh:
        doc = tomllib.load(fh)
    taken = doc.get("taken")
    rows = doc.get("models")
    if not isinstance(taken, dt.date) or not isinstance(rows, list):
        raise CatalogError(f"{path.name} needs a `taken` date and [[models]] entries.")
    return Catalog(taken.isoformat(), tuple(_entry(i, row) for i, row in enumerate(rows)))


def _entry(index: int, row: Any) -> LocalModel:
    if not isinstance(row, dict) or set(row) != set(_FIELDS):
        raise CatalogError(f"Entry {index + 1} must have exactly: {', '.join(_FIELDS)}.")
    values: dict[str, Any] = {}
    for name, kind in _FIELDS.items():
        value = row[name]
        if kind is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise CatalogError(f"Entry {index + 1}: {name} must be a {kind.__name__}.")
        values[name] = value
    if values["kind"] not in KINDS:
        raise CatalogError(f"Entry {index + 1}: kind is one of {', '.join(KINDS)}.")
    return LocalModel(**values)


def memory_bytes() -> int:
    """This Mac's memory, from the kernel; no subprocess."""
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def fit(model: LocalModel, memory: int) -> Fit:
    """How the model fits a Mac with `memory` bytes (see the file's header)."""
    if memory >= model.memory_gb * GIB:
        return "comfortable"
    if model.size_bytes + TIGHT_EXTRA_BYTES <= memory * GPU_SHARE:
        return "tight"
    return "too_big"


def recommend(catalog: Catalog, memory: int) -> LocalModel | None:
    """The best general entry that fits comfortably, one that can use tools first."""
    comfortable = [m for m in catalog.models if m.kind == "general" and fit(m, memory) == "comfortable"]
    with_tools = [m for m in comfortable if m.tools]
    chosen = with_tools or comfortable
    return chosen[-1] if chosen else None


def is_small(repo: str, size: int | None) -> bool:
    """A small model calls tools better from a short list. The catalog's size when listed,
    else the size on disk; an unknown model of unknown size counts as not small."""
    entry = load_catalog().get(repo)
    known = entry.size_bytes if entry is not None else size
    return known is not None and known < SMALL_BYTES


def listing(memory: int) -> dict[str, Any]:
    """The catalog as the window gets it, without what is on disk (the settings add that)."""
    catalog = load_catalog()
    best = recommend(catalog, memory)
    return {
        "taken": catalog.taken,
        "memory_bytes": memory,
        "recommended": best.id if best else None,
        "models": [{**asdict(m), "fit": fit(m, memory)} for m in catalog.models],
    }
