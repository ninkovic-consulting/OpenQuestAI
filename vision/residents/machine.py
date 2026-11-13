"""The steward's `machine_status`: disk, memory, battery, uptime and load of this Mac.

Read-only and quick. Disk, load and uptime come from the standard library
and the kernel's `sysctl` values (through `ctypes`, no program is started);
the battery from `pmset -g batt`, the one outside program, stopped after a
few seconds if it does not answer. Everything goes through `Probe`, which
the tests fake.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vision.gate.tools import run_command

BATTERY_TIMEOUT_S = 3.0
GB = 1024**3


@dataclass(frozen=True, slots=True)
class Reading:
    disk_total: int
    disk_free: int
    memory_total: int | None
    memory_free: int | None
    """Free pages only; macOS keeps much memory as reclaimable cache, which this leaves out."""
    boot_time: float | None
    load: tuple[float, float, float]
    battery: str | None
    """`pmset`'s own words, such as "82%; discharging; 4:10 remaining", or None."""


class Probe(Protocol):
    async def read(self) -> Reading: ...


class MacProbe:
    def __init__(self, disk: Path | None = None) -> None:
        self._disk = disk or Path.home()

    async def read(self) -> Reading:
        usage = shutil.disk_usage(self._disk)
        page = _sysctl_int("hw.pagesize")
        free_pages = _sysctl_int("vm.page_free_count")
        return Reading(
            disk_total=usage.total,
            disk_free=usage.free,
            memory_total=_sysctl_int("hw.memsize"),
            memory_free=page * free_pages if page and free_pages is not None else None,
            boot_time=_boot_time(),
            load=os.getloadavg(),
            battery=await _battery(),
        )


def _libc() -> ctypes.CDLL | None:
    name = ctypes.util.find_library("c")
    return ctypes.CDLL(name, use_errno=True) if name else None


def _sysctl(name: str, size: int) -> bytes | None:
    libc = _libc()
    if libc is None:
        return None
    buf = ctypes.create_string_buffer(size)
    length = ctypes.c_size_t(size)
    if libc.sysctlbyname(name.encode(), buf, ctypes.byref(length), None, ctypes.c_size_t(0)) != 0:
        return None
    return buf.raw[: length.value]


def _sysctl_int(name: str) -> int | None:
    raw = _sysctl(name, 8)
    return int.from_bytes(raw, "little") if raw else None


def _boot_time() -> float | None:
    raw = _sysctl("kern.boottime", 16)  # struct timeval: seconds, then microseconds
    if not raw or len(raw) < 8:
        return None
    return float(int.from_bytes(raw[:8], "little"))


async def _battery() -> str | None:
    try:
        result = await run_command(["pmset", "-g", "batt"], timeout=BATTERY_TIMEOUT_S, limit=2000)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    found = re.search(r"\t(\d+%;[^\n]*)", result.output)
    if found is None:
        return None
    words = re.sub(r"\s*present: true\s*$", "", found.group(1)).strip()
    source = "on AC power" if "AC Power" in result.output else "on battery"
    return f"{words} ({source})"


def describe(r: Reading, now: float | None = None) -> str:
    now = time.time() if now is None else now
    lines = [
        f"Disk (home volume): {r.disk_free / GB:.1f} GB free of {r.disk_total / GB:.1f} GB "
        f"({r.disk_free / r.disk_total:.0%} free).",
    ]
    if r.memory_total:
        free = f"; {r.memory_free / GB:.1f} GB not in use at all (cache not counted)" if r.memory_free is not None else ""
        lines.append(f"Memory: {r.memory_total / GB:.0f} GB{free}.")
    if r.boot_time:
        up = max(0.0, now - r.boot_time)
        days, rest = divmod(int(up), 86_400)
        hours, minutes = rest // 3600, rest % 3600 // 60
        lines.append(f"Up for {_count(days, 'day')}, {_count(hours, 'hour')} and {_count(minutes, 'minute')}.")
    lines.append(f"Load (1, 5, 15 minutes): {r.load[0]:.2f}, {r.load[1]:.2f}, {r.load[2]:.2f}.")
    lines.append(f"Battery: {r.battery}." if r.battery else "Battery: none found, or it could not be read.")
    return "\n".join(lines)


def _count(n: int, unit: str) -> str:
    return f"{n} {unit}" + ("" if n == 1 else "s")
