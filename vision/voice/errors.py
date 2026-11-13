"""Why voice cannot run, worded for the notice the daemon shows (spec section 7)."""

from __future__ import annotations

import os
import sys

MIC_SETTING = "System Settings > Privacy & Security > Microphone"
APP_ENV = "VISION_APP"
"""Set by the Mac app to its own name when it starts the daemon (macos/Sources/DaemonProcess.swift)."""


class VoiceUnavailable(RuntimeError):
    """Voice cannot start. The message says why and what to change."""


def _runner() -> str:
    """The app macOS asks about the microphone: the Mac app by name when it started the daemon."""
    app = os.environ.get(APP_ENV, "").strip()
    if app:
        return app
    return (
        "the app that runs the assistant (your terminal when started by hand; for the "
        f"background service, {sys.executable})"
    )


def mic_permission_hint() -> str:
    return f"Allow microphone access in {MIC_SETTING}: turn it on for {_runner()}, then restart it."


def silent_mic_hint() -> str:
    """What to try when a microphone opens but sends only zeros.

    On a Mac that has the permission, silence is nearly always the device:
    muted, asleep, covered, or a laptop's own microphone with the lid closed.
    macOS also hands an app without the permission pure zeros, so that stays
    on the list, last.
    """
    return (
        "It may be muted, asleep or covered: a webcam in privacy mode, or a laptop's own "
        "microphone with the lid closed. Choose another microphone in Settings, Voice. If no "
        f"microphone works, check that {_runner()} may use the microphone in {MIC_SETTING}."
    )
