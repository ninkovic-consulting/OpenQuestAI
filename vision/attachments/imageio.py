"""Reading and re-drawing an image with macOS ImageIO, through `ctypes`.

Nothing is installed for this: ImageIO and CoreFoundation ship with macOS and
are what Preview and `sips` use, so every format Vision accepts (PNG, JPEG,
GIF, WebP) is read by the system's own, hardened decoders. Pillow is not in
the dependencies, and pyobjc only comes with the window's extra, so the
daemon calls the C functions directly, as `vision.presence.reader` does.

Two operations:

- `probe` reads only the header: the format ImageIO recognised, the frame
  count and the pixel size. Nothing is decoded, so an image that claims a
  huge size is refused before it can take memory.
- `redraw` decodes the first frame, applies its EXIF orientation, scales it so
  the long edge is at most `max_edge` (never up), and encodes a new file from
  the pixels alone. No property dictionary is copied, so EXIF, GPS, IPTC, XMP
  and comments are left behind, and anything appended to or hidden in the
  original file (a polyglot's second payload) cannot survive.
"""

from __future__ import annotations

import ctypes
import threading
from dataclasses import dataclass
from functools import cache

IMAGE_IO = "/System/Library/Frameworks/ImageIO.framework/ImageIO"
CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
UTF8 = 0x08000100
SINT64 = 4
FLOAT64 = 6
PNG_UTI = "public.png"
JPEG_UTI = "public.jpeg"


class Unreadable(Exception):
    """ImageIO could not read or write the image. The text is for the log, not for people."""


@dataclass(frozen=True, slots=True)
class Header:
    uti: str
    """The type ImageIO recognised, e.g. `public.png`, `org.webmproject.webp`."""
    frames: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Drawn:
    data: bytes
    uti: str
    width: int
    height: int


class _Frameworks:
    """The C functions, typed once per process."""

    def __init__(self) -> None:
        io, cg, cf = ctypes.CDLL(IMAGE_IO), ctypes.CDLL(CORE_GRAPHICS), ctypes.CDLL(CORE_FOUNDATION)
        p, n, b = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_bool
        for fn, res, args in (
            (cf.CFDataCreate, p, [p, ctypes.c_char_p, ctypes.c_long]),
            (cf.CFDataCreateMutable, p, [p, ctypes.c_long]),
            (cf.CFDataGetLength, ctypes.c_long, [p]),
            (cf.CFDataGetBytePtr, p, [p]),
            (cf.CFStringCreateWithCString, p, [p, ctypes.c_char_p, ctypes.c_uint32]),
            (cf.CFStringGetCString, b, [p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]),
            (cf.CFNumberCreate, p, [p, ctypes.c_int, p]),
            (cf.CFNumberGetValue, b, [p, ctypes.c_int, p]),
            (cf.CFDictionaryCreate, p, [p, p, p, ctypes.c_long, p, p]),
            (cf.CFDictionaryGetValue, p, [p, p]),
            (cf.CFRelease, None, [p]),
            (io.CGImageSourceCreateWithData, p, [p, p]),
            (io.CGImageSourceGetType, p, [p]),
            (io.CGImageSourceGetCount, n, [p]),
            (io.CGImageSourceCopyPropertiesAtIndex, p, [p, n, p]),
            (io.CGImageSourceCreateThumbnailAtIndex, p, [p, n, p]),
            (io.CGImageDestinationCreateWithData, p, [p, p, n, p]),
            (io.CGImageDestinationAddImage, None, [p, p, p]),
            (io.CGImageDestinationFinalize, b, [p]),
            (cg.CGImageGetWidth, n, [p]),
            (cg.CGImageGetHeight, n, [p]),
            (cg.CGImageRelease, None, [p]),
        ):
            fn.restype, fn.argtypes = res, args
        self.io, self.cg, self.cf = io, cg, cf

        def const(lib: ctypes.CDLL, name: str) -> int:
            value = ctypes.c_void_p.in_dll(lib, name).value
            if not value:
                raise OSError(f"{name} is missing")
            return value

        self.width_key = const(io, "kCGImagePropertyPixelWidth")
        self.height_key = const(io, "kCGImagePropertyPixelHeight")
        self.always = const(io, "kCGImageSourceCreateThumbnailFromImageAlways")
        self.max_size = const(io, "kCGImageSourceThumbnailMaxPixelSize")
        self.transform = const(io, "kCGImageSourceCreateThumbnailWithTransform")
        self.quality = const(io, "kCGImageDestinationLossyCompressionQuality")
        self.true = const(cf, "kCFBooleanTrue")
        self.key_callbacks = ctypes.addressof(ctypes.c_byte.in_dll(cf, "kCFTypeDictionaryKeyCallBacks"))
        self.value_callbacks = ctypes.addressof(ctypes.c_byte.in_dll(cf, "kCFTypeDictionaryValueCallBacks"))
        self.lock = threading.Lock()
        """ImageIO is thread-safe; the lock only keeps one large decode in memory at a time."""

    # ------------------------------------------------------------ CoreFoundation helpers

    def string(self, text: str) -> int:
        return self.cf.CFStringCreateWithCString(None, text.encode(), UTF8)

    def text(self, ref: int) -> str:
        buf = ctypes.create_string_buffer(256)
        return buf.value.decode() if self.cf.CFStringGetCString(ref, buf, len(buf), UTF8) else ""

    def number(self, value: float, kind: int) -> int:
        cell = ctypes.c_double(value) if kind == FLOAT64 else ctypes.c_int64(int(value))
        return self.cf.CFNumberCreate(None, kind, ctypes.byref(cell))

    def integer(self, ref: int | None) -> int:
        cell = ctypes.c_int64(0)
        if not ref or not self.cf.CFNumberGetValue(ref, SINT64, ctypes.byref(cell)):
            return 0
        return cell.value

    def dictionary(self, pairs: list[tuple[int, int]]) -> int:
        keys = (ctypes.c_void_p * len(pairs))(*[k for k, _ in pairs])
        values = (ctypes.c_void_p * len(pairs))(*[v for _, v in pairs])
        return self.cf.CFDictionaryCreate(None, keys, values, len(pairs), self.key_callbacks, self.value_callbacks)

    def source(self, data: bytes) -> tuple[int, int]:
        """A CFData and an image source over it; the caller releases both."""
        blob = self.cf.CFDataCreate(None, data, len(data))
        if not blob:
            raise Unreadable("no memory for the image data")
        src = self.io.CGImageSourceCreateWithData(blob, None)
        if not src:
            self.cf.CFRelease(blob)
            raise Unreadable("ImageIO did not take the data")
        return blob, src


@cache
def _frameworks() -> _Frameworks:
    try:
        return _Frameworks()
    except (OSError, AttributeError, ValueError) as exc:
        raise Unreadable(f"ImageIO is not available here ({exc})") from exc


def probe(data: bytes) -> Header:
    """The format, frame count and pixel size from the header, without decoding."""
    fw = _frameworks()
    blob, src = fw.source(data)
    try:
        kind = fw.io.CGImageSourceGetType(src)
        frames = int(fw.io.CGImageSourceGetCount(src))
        props = fw.io.CGImageSourceCopyPropertiesAtIndex(src, 0, None) if frames else None
        if not kind or not props:
            raise Unreadable("not an image ImageIO can read")
        try:
            width = fw.integer(fw.cf.CFDictionaryGetValue(props, fw.width_key))
            height = fw.integer(fw.cf.CFDictionaryGetValue(props, fw.height_key))
        finally:
            fw.cf.CFRelease(props)
        if width <= 0 or height <= 0:
            raise Unreadable("the image has no size")
        return Header(fw.text(kind), frames, width, height)
    finally:
        fw.cf.CFRelease(src)
        fw.cf.CFRelease(blob)


def redraw(data: bytes, *, max_edge: int, uti: str, quality: float = 0.9) -> Drawn:
    """The first frame, turned upright, at most `max_edge` on its long side, encoded as `uti`
    (`public.png` or `public.jpeg`) from the pixels alone."""
    fw = _frameworks()
    header = probe(data)
    edge = min(max_edge, max(header.width, header.height))
    with fw.lock:
        blob, src = fw.source(data)
        made: list[int] = []
        image = None
        try:
            size = fw.number(edge, SINT64)
            made.append(size)
            options = fw.dictionary([(fw.always, fw.true), (fw.transform, fw.true), (fw.max_size, size)])
            made.append(options)
            image = fw.io.CGImageSourceCreateThumbnailAtIndex(src, 0, options)
            if not image:
                raise Unreadable("ImageIO could not decode the image")
            out = fw.cf.CFDataCreateMutable(None, 0)
            made.append(out)
            kind = fw.string(uti)
            made.append(kind)
            dest = fw.io.CGImageDestinationCreateWithData(out, kind, 1, None)
            if not dest:
                raise Unreadable(f"ImageIO cannot write {uti}")
            made.append(dest)
            props = None
            if uti == JPEG_UTI:
                level = fw.number(quality, FLOAT64)
                made.append(level)
                props = fw.dictionary([(fw.quality, level)])
                made.append(props)
            fw.io.CGImageDestinationAddImage(dest, image, props)
            if not fw.io.CGImageDestinationFinalize(dest):
                raise Unreadable("ImageIO could not encode the image")
            length = fw.cf.CFDataGetLength(out)
            encoded = ctypes.string_at(fw.cf.CFDataGetBytePtr(out), length)
            return Drawn(encoded, uti, int(fw.cg.CGImageGetWidth(image)), int(fw.cg.CGImageGetHeight(image)))
        finally:
            if image:
                fw.cg.CGImageRelease(image)
            for ref in reversed(made):
                fw.cf.CFRelease(ref)
            fw.cf.CFRelease(src)
            fw.cf.CFRelease(blob)
