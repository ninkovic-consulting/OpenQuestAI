"""Tiny images built in the tests: PNG by hand, the rest from fixed bytes or through ImageIO."""

from __future__ import annotations

import base64
import struct
import zlib
from functools import cache

from vision.attachments import imageio

GIF_1PX = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
WEBP_1PX = base64.b64decode("UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")
SECRET = b"SECRET-PLACE-48N"
"""Written into a test JPEG's EXIF description; must never survive cleaning."""


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width: int, height: int, rgb: tuple[int, int, int] = (200, 30, 30), *, idat: bytes | None = None) -> bytes:
    """A solid RGB PNG. `idat` replaces the pixel data."""
    if idat is None:
        row = b"\x00" + bytes(rgb) * width
        idat = zlib.compress(row * height)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


@cache
def bomb() -> bytes:
    """A 10,000 by 6,000 PNG of zeros: 60 megapixels in about 175 KB."""
    pack = zlib.compressobj(9)
    row = b"\x00" * (1 + 3 * 10_000)
    idat = b"".join(pack.compress(row) for _ in range(6_000)) + pack.flush()
    return png(10_000, 6_000, idat=idat)


def jpeg(width: int = 40, height: int = 30) -> bytes:
    return imageio.redraw(png(width, height), max_edge=4000, uti=imageio.JPEG_UTI).data


def _exif() -> bytes:
    """An APP1 segment: IFD0 with an ImageDescription and a GPS IFD (latitude 48 N)."""
    ifd0, gps, lat, desc = 8, 38, 68, 92
    text = SECRET + b"\x00"
    tiff = b"MM\x00\x2a" + struct.pack(">I", ifd0)
    tiff += struct.pack(">H", 2)
    tiff += struct.pack(">HHII", 0x010E, 2, len(text), desc)
    tiff += struct.pack(">HHII", 0x8825, 4, 1, gps)
    tiff += struct.pack(">I", 0)
    tiff += struct.pack(">H", 2)
    tiff += struct.pack(">HHI", 0x0001, 2, 2) + b"N\x00\x00\x00"
    tiff += struct.pack(">HHII", 0x0002, 5, 3, lat)
    tiff += struct.pack(">I", 0)
    tiff += struct.pack(">IIIIII", 48, 1, 12, 1, 0, 1)
    tiff += text
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def jpeg_with_location(width: int = 40, height: int = 30) -> bytes:
    """A JPEG carrying EXIF with GPS and a description, as a phone photo would."""
    plain = jpeg(width, height)
    return plain[:2] + _exif() + plain[2:]


def app_segments(data: bytes) -> list[bytes]:
    """The payloads of a JPEG's APPn segments, up to the image data."""
    found, i = [], 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker, size = data[i + 1], struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker == 0xDA:
            break
        if 0xE0 <= marker <= 0xEF:
            found.append(data[i + 4 : i + 2 + size])
        i += 2 + size
    return found
