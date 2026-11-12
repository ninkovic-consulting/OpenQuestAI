"""Why voice cannot run, worded for the notice the daemon shows (spec section 7)."""

from __future__ import annotations

import sys

MIC_SETTING = "System Settings > Privacy & Security > Microphone"


class VoiceUnavailable(RuntimeError):
    """Voice cannot start. The message says why and what to change."""


def mic_permission_hint() -> str:
    return (
        f"Allow microphone access in {MIC_SETTING}: turn it on for the app that runs "
        f"the assistant (your terminal when started by hand; for the background "
        f"service, {sys.executable}), then restart it."
    )
