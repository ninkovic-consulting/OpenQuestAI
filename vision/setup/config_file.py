"""Write a few values into `config.toml`, keeping everything else in it."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from vision.house import store


def update_config(path: Path, section: str, values: dict[str, Any]) -> None:
    """Set `values` in `[section]`. Comments in the file are not kept."""
    doc: dict[str, Any] = {}
    if path.is_file():
        with path.open("rb") as fh:
            doc = tomllib.load(fh)
    doc[section] = {**doc.get(section, {}), **values}
    store.write_toml(path, doc)
