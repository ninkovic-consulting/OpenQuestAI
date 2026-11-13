"""The audio devices as they are right now: `python -m vision.voice.devices` prints them as JSON.

PortAudio reads the device list once, when it initialises, so a process that
has been running keeps the list it started with: AirPods connected later
never show. The daemon cannot initialise PortAudio again while the
microphone is open (that would break the stream), so the settings screen
asks a short-lived child process, which always starts with the current list.
Listing opens no device.
"""

from __future__ import annotations

import json
from typing import Any


def current() -> list[dict[str, Any]]:
    """Every device with its channel counts and whether it is a system default."""
    import sounddevice

    default_in, default_out = sounddevice.default.device
    return [
        {
            "name": str(dev["name"]),
            "inputs": int(dev["max_input_channels"]),
            "outputs": int(dev["max_output_channels"]),
            "default_input": index == default_in,
            "default_output": index == default_out,
        }
        for index, dev in enumerate(sounddevice.query_devices())
    ]


def main() -> None:
    print(json.dumps(current()))


if __name__ == "__main__":
    main()
