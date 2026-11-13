"""Which audio devices are Bluetooth, and whether microphone and speakers are one headset.

PortAudio names devices but does not say how they are connected, so this
asks macOS: `system_profiler SPAudioDataType -json` lists every Core Audio
device with its transport (`coreaudio_device_transport`), which is
`coreaudio_device_type_bluetooth` for AirPods and other headsets. It takes
about a fifth of a second and opens no device. A headset is the same device
for input and output, under one name, so "the chosen microphone and speakers
are one Bluetooth headset" is: the two names are the same, and it is
Bluetooth.

Why it matters: while a Bluetooth headset's microphone is open, macOS plays
through it in the hands-free call profile, which sounds thin and choppy, and
switching profiles can drop the first moment of audio.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

BLUETOOTH = "coreaudio_device_type_bluetooth"
TIMEOUT_S = 5.0
SETTLE_S = 0.3
"""After a headset's microphone closes, the moment it takes to play well again."""

Run = Callable[..., subprocess.CompletedProcess[str]]


def bluetooth_names(run: Run = subprocess.run) -> frozenset[str]:
    """The names of the audio devices connected over Bluetooth now; empty when macOS will not say."""
    try:
        done = run(
            ["system_profiler", "SPAudioDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=True,
        )
        data: dict[str, Any] = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        log.info("could not ask macOS which audio devices are Bluetooth: %s", exc)
        return frozenset()
    return frozenset(
        str(item.get("_name", ""))
        for group in data.get("SPAudioDataType", [])
        for item in group.get("_items", [])
        if item.get("coreaudio_device_transport") == BLUETOOTH
    )


def one_headset(microphone: str, speakers: str, bluetooth: frozenset[str]) -> bool:
    """True when the microphone and the speakers are the same Bluetooth headset."""
    return bool(microphone) and microphone == speakers and microphone in bluetooth


def chosen_are_one_headset(input_device: str, output_device: str) -> bool:
    """Whether the configured microphone and speakers (as PortAudio resolves them now) are one
    Bluetooth headset. Blocking: it lists the devices and asks macOS."""
    from vision.voice.audio_io import device_name, resolve_device

    try:
        microphone = device_name(resolve_device(input_device, "input")[0], "input")
        speakers = device_name(resolve_device(output_device, "output")[0], "output")
    except Exception as exc:  # no devices at all: nothing to share
        log.info("could not resolve the audio devices: %s", exc)
        return False
    return one_headset(microphone, speakers, bluetooth_names())
