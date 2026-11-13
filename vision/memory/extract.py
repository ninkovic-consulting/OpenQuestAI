"""Text out of a file the owner adds to the library: plain text, Markdown, PDF and Word.

The text is taken once, when the file is added; the original is kept beside
it. Each reader refuses with `Unreadable`, whose message is for people: a
file past the caps, a scanned PDF with no text in it, a password, a broken
file. Word files are read with the standard library (a `.docx` is a zip of
XML); PDFs with `pypdf`, a small pure-Python reader, since the standard
library cannot decode a PDF's text. Blocking.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal
from xml.etree import ElementTree

log = logging.getLogger(__name__)

Kind = Literal["markdown", "text", "pdf", "docx"]
KINDS: dict[str, Kind] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".text": "text",
    ".pdf": "pdf",
    ".docx": "docx",
}
"""File endings the library takes, and the kind each makes."""
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 400_000
"""About a hundred thousand tokens: more than any conversation should read whole."""
MAX_PAGES = 1000
_DOCX_XML_BYTES = 60 * 1024 * 1024
"""The most `word/document.xml` may unpack to, so a zip bomb is refused unread."""
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Unreadable(ValueError):
    """The file cannot be added; the message says why, for people."""


@dataclass(frozen=True, slots=True)
class Extracted:
    kind: Kind
    text: str


def kind_of(filename: str) -> Kind:
    """The kind a file's ending makes. Raises `Unreadable` for any other ending."""
    kind = KINDS.get(PurePath(filename).suffix.casefold())
    if kind is None:
        raise Unreadable(
            "The library takes text (.txt), Markdown (.md), PDF (.pdf) and Word (.docx) files."
        )
    return kind


def extract(filename: str, data: bytes) -> Extracted:
    """The file's text, tidied. Raises `Unreadable`."""
    kind = kind_of(filename)
    if len(data) > MAX_FILE_BYTES:
        raise Unreadable(
            f"The file is {_mb(len(data))}; the library takes files up to {_mb(MAX_FILE_BYTES)}."
        )
    if not data:
        raise Unreadable("The file is empty.")
    if kind == "pdf":
        text = _pdf(data)
    elif kind == "docx":
        text = _docx(data)
    else:
        text = _plain(data)
    text = tidy(text)
    if not text:
        raise Unreadable("There is no text in the file.")
    check_size(text)
    return Extracted(kind, text)


def check_size(text: str) -> None:
    if len(text) > MAX_TEXT_CHARS:
        raise Unreadable(
            f"The text is {len(text):,} characters; the library keeps documents of up to "
            f"{MAX_TEXT_CHARS:,} characters. Split it into parts and add them one by one."
        )


def tidy(text: str) -> str:
    """Unix line ends, no trailing spaces, no runs of blank lines, no control characters."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def _plain(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise Unreadable("The file is not UTF-8 text. Save it as UTF-8 and add it again.") from None


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise Unreadable("The PDF is locked with a password. Save a copy without it and add that.")
        if len(reader.pages) > MAX_PAGES:
            raise Unreadable(f"The PDF has {len(reader.pages):,} pages; the library takes up to {MAX_PAGES:,}.")
        pages: list[str] = []
        size = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            size += len(text)
            if size > MAX_TEXT_CHARS * 2:
                break
            pages.append(text)
    except Unreadable:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        log.info("a PDF could not be read: %s", type(exc).__name__)
        raise Unreadable("The PDF could not be read; it may be damaged.") from None
    if not tidy("\n\n".join(pages)):
        raise Unreadable(
            "The PDF has no text in it: it looks like scanned pages, which the library cannot "
            "read. Add a PDF with selectable text, or the text itself."
        )
    return "\n\n".join(pages)


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _DOCX_XML_BYTES:
                raise Unreadable("The Word file is too large inside to read.")
            xml = archive.read(info)
    except Unreadable:
        raise
    except (zipfile.BadZipFile, KeyError, OSError, RuntimeError):
        raise Unreadable(
            "The file is not a Word document (.docx). An older .doc file can be saved as .docx first."
        ) from None
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise Unreadable("The Word file could not be read; it may be damaged.") from None
    body = root.find(f"{_W}body")
    if body is None:
        return ""
    lines: list[str] = []
    for paragraph in body.iter(f"{_W}p"):
        lines.append(_runs(paragraph))
    return "\n\n".join(line for line in lines if line.strip())


def _runs(paragraph: ElementTree.Element) -> str:
    out: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            out.append(node.text)
        elif node.tag == f"{_W}tab":
            out.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            out.append("\n")
    return "".join(out)
