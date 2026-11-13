"""The owner's images, kept under `$VISION_HOME/images/`.

Each accepted image is kept once, as its clean copy (`clean.clean`): the
original is never written. The folder is 0700 and every file 0600, written
through a temporary file and a rename, and named `<id>.png` or `<id>.jpg`
where the id is 32 random hex characters, so a name never comes from the
sender. Nothing here is ever executed or served but by the token-checked
routes (`routes.py`) to the owner's own window.

The images are part of the conversation: the log names the ones each turn
carried, and the backups and reset levels treat the folder like `log.db`.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from vision.attachments.clean import clean
from vision.attachments.imageio import Unreadable, probe
from vision.core.interfaces import Picture

ID = re.compile(r"^[0-9a-f]{32}$")
_ENDINGS = {"image/png": ".png", "image/jpeg": ".jpg"}
_TYPES = {ending: kind for kind, ending in _ENDINGS.items()}


class NoSuchImage(LookupError):
    """No image is kept under that id (never sent, or removed)."""


class ImageStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def add(self, data: bytes) -> Picture:
        """Check, clean and keep an image. Raises `clean.ImageRefused`. Blocking."""
        cleaned = clean(data)
        image_id = uuid.uuid4().hex
        self._write(self.folder / f"{image_id}{_ENDINGS[cleaned.media_type]}", cleaned.data)
        return Picture(image_id, cleaned.media_type, cleaned.width, cleaned.height, cleaned.data)

    def get(self, image_id: str) -> Picture:
        """The kept image. Raises `NoSuchImage`. Blocking."""
        path = self._path(image_id)
        try:
            data = path.read_bytes()
            header = probe(data)
        except (OSError, Unreadable) as exc:
            raise NoSuchImage(image_id) from exc
        return Picture(image_id, _TYPES[path.suffix], header.width, header.height, data)

    def raw(self, image_id: str) -> tuple[bytes, str]:
        """The file's bytes and media type, for the window. Raises `NoSuchImage`. Blocking."""
        path = self._path(image_id)
        try:
            return path.read_bytes(), _TYPES[path.suffix]
        except OSError as exc:
            raise NoSuchImage(image_id) from exc

    def remove(self, image_id: str) -> None:
        """Delete the image's file. Raises `NoSuchImage`. The log still names it; the window
        shows it as removed."""
        try:
            self._path(image_id).unlink()
        except FileNotFoundError as exc:
            raise NoSuchImage(image_id) from exc

    def _path(self, image_id: str) -> Path:
        if ID.match(image_id):
            for ending in _TYPES:
                path = self.folder / f"{image_id}{ending}"
                if path.is_file():
                    return path
        raise NoSuchImage(image_id)

    def _write(self, path: Path, data: bytes) -> None:
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.folder, 0o700)
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
