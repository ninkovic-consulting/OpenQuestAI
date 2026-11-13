"""What an image must be to be kept, and the clean copy that is kept instead of it.

An image is accepted only when its first bytes say PNG, JPEG, GIF or WebP
(never its name or declared type), ImageIO reads the same format from it, and
it is within the limits below. It is then drawn again (`imageio.redraw`):
upright, scaled down so the long edge is at most `LONG_EDGE`, and encoded from
its pixels alone, which strips every kind of metadata, location included.
A JPEG stays a JPEG; the others become PNG (an animated GIF keeps its first
frame, which is all Claude reads of one anyway).

`LONG_EDGE` is the standard tier's long edge in Claude's vision guide: the
high-resolution models would take up to 2,576 px, but at 1,568 px text in a
screenshot or a photo of a page still reads and an image costs at most about
3,100 visual tokens instead of 4,784.
"""

from __future__ import annotations

from dataclasses import dataclass

from vision.attachments import imageio
from vision.core.events import MAX_IMAGES

MAX_BYTES = 15 * 1024 * 1024
"""The most an uploaded file may weigh: a phone photo is 2 to 8 MB."""
MAX_PIXELS = 50_000_000
"""Read from the header before anything is decoded, so a small file claiming a huge size
(a decompression bomb) is refused cheaply."""
MAX_PER_MESSAGE = MAX_IMAGES
"""Checked where a message is read (`input.text`, `user.utterance`); here for the window."""
LONG_EDGE = 1568
MAX_PNG_BYTES = 5 * 1024 * 1024
"""A redrawn PNG larger than this (a noisy photo with transparency) is sent as JPEG instead,
well under the API's 10 MB per image."""

MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
_UTI = {
    "image/png": "public.png",
    "image/jpeg": "public.jpeg",
    "image/gif": "com.compuserve.gif",
    "image/webp": "org.webmproject.webp",
}
_OUT = {imageio.PNG_UTI: "image/png", imageio.JPEG_UTI: "image/jpeg"}

NOT_AN_IMAGE = "That file is not a PNG, JPEG, GIF or WebP image."
TOO_BIG = f"That image is larger than {MAX_BYTES // (1024 * 1024)} MB."
TOO_MANY_PIXELS = f"That image has more than {MAX_PIXELS // 1_000_000} megapixels."
EMPTY = "That file is empty."
UNREADABLE = "That image could not be read; it may be damaged."


class ImageRefused(ValueError):
    """The image is not kept. The text is one plain sentence for people."""


@dataclass(frozen=True, slots=True)
class Cleaned:
    data: bytes
    media_type: str
    width: int
    height: int


def sniff(data: bytes) -> str | None:
    """The media type the first bytes say, or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def limits() -> dict[str, object]:
    """The limits as the window reads them (`GET /api/images/limits`)."""
    return {
        "types": list(MEDIA_TYPES),
        "max_bytes": MAX_BYTES,
        "max_pixels": MAX_PIXELS,
        "max_per_message": MAX_PER_MESSAGE,
        "long_edge": LONG_EDGE,
    }


def clean(data: bytes) -> Cleaned:
    """The clean copy of an accepted image. Raises `ImageRefused`. Blocking: run off the loop."""
    if not data:
        raise ImageRefused(EMPTY)
    if len(data) > MAX_BYTES:
        raise ImageRefused(TOO_BIG)
    kind = sniff(data)
    if kind is None:
        raise ImageRefused(NOT_AN_IMAGE)
    try:
        header = imageio.probe(data)
    except imageio.Unreadable as exc:
        raise ImageRefused(UNREADABLE) from exc
    if header.uti != _UTI[kind]:
        raise ImageRefused(NOT_AN_IMAGE)
    if header.width * header.height > MAX_PIXELS:
        raise ImageRefused(TOO_MANY_PIXELS)
    out = imageio.JPEG_UTI if kind == "image/jpeg" else imageio.PNG_UTI
    try:
        drawn = imageio.redraw(data, max_edge=LONG_EDGE, uti=out)
        if drawn.uti == imageio.PNG_UTI and len(drawn.data) > MAX_PNG_BYTES:
            drawn = imageio.redraw(data, max_edge=LONG_EDGE, uti=imageio.JPEG_UTI)
    except imageio.Unreadable as exc:
        raise ImageRefused(UNREADABLE) from exc
    return Cleaned(drawn.data, _OUT[drawn.uti], drawn.width, drawn.height)
