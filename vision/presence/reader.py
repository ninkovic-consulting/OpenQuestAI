"""Reading, without any macOS permission, how long the Mac has gone without input.

`MacReader` calls three CoreGraphics functions through `ctypes`, so nothing is
installed and no permission is asked for (not Accessibility, not Input
Monitoring, not Screen Recording):

- `CGEventSourceSecondsSinceLastEventType(combined session state, any input)`:
  seconds since the last keyboard, mouse or trackpad event in this login
  session. It returns a number only, never what was typed.
- `CGSessionCopyCurrentDictionary()`, key `CGSSessionScreenIsLocked`: the
  screen is locked. No dictionary means the process is outside a login
  session (over SSH, say), and then nothing here can be known.
- `CGDisplayIsAsleep(CGMainDisplayID())`: the main display sleeps.

A read costs about a third of a millisecond, most of it the session
dictionary, after the frameworks load once (about 40 ms, on the first read).
Whatever cannot be read comes back as None.
"""

from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
COMBINED_SESSION_STATE = 0
ANY_INPUT_EVENT = 0xFFFFFFFF
UTF8 = 0x08000100
LOCKED_KEY = b"CGSSessionScreenIsLocked"


@dataclass(frozen=True, slots=True)
class Reading:
    idle_s: float | None
    """Seconds since the last keyboard or mouse input, or None when unknown."""
    locked: bool | None
    asleep: bool | None
    """The main display sleeps."""

    @property
    def known(self) -> bool:
        return self.idle_s is not None or self.locked is not None or self.asleep is not None


UNKNOWN = Reading(None, None, None)


class Reader(Protocol):
    def read(self) -> Reading: ...


class _Frameworks:
    def __init__(self) -> None:
        cg = ctypes.CDLL(CORE_GRAPHICS)
        cf = ctypes.CDLL(CORE_FOUNDATION)
        cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
        cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_int32, ctypes.c_uint32]
        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        cg.CGSessionCopyCurrentDictionary.argtypes = []
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayIsAsleep.restype = ctypes.c_bool
        cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cg, self.cf = cg, cf
        self.locked_key = cf.CFStringCreateWithCString(None, LOCKED_KEY, UTF8)
        """Kept for the life of the process: it is made once."""


class MacReader:
    """The real reader. A Mac where the frameworks cannot be loaded reads as unknown."""

    def __init__(self) -> None:
        self._fw: _Frameworks | None = None
        self._failed = False

    def read(self) -> Reading:
        fw = self._frameworks()
        if fw is None:
            return UNKNOWN
        session = fw.cg.CGSessionCopyCurrentDictionary()
        if not session:
            return UNKNOWN
        try:
            value = fw.cf.CFDictionaryGetValue(session, fw.locked_key)
            locked = bool(value) and fw.cf.CFBooleanGetValue(value)
        finally:
            fw.cf.CFRelease(session)
        idle = fw.cg.CGEventSourceSecondsSinceLastEventType(COMBINED_SESSION_STATE, ANY_INPUT_EVENT)
        asleep = fw.cg.CGDisplayIsAsleep(fw.cg.CGMainDisplayID())
        return Reading(idle if idle >= 0 else None, locked, asleep)

    def _frameworks(self) -> _Frameworks | None:
        if self._fw is None and not self._failed:
            try:
                self._fw = _Frameworks()
            except (OSError, AttributeError) as exc:
                log.warning("presence cannot be read on this machine (%s); the owner counts as present", exc)
                self._failed = True
        return self._fw
