"""Voice: microphone, VAD, wake matching, speech recognition and speech.

The composition root (`vision.app`) calls `make_voice`. Until it is
implemented it raises `NotImplementedError` and the daemon runs text-only
with `vision.testing.fakes.FakeVoice` (a silent speaker), publishing a notice.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Voice


def make_voice(config: Config, bus: Bus) -> Voice:
    """Build the voice loop and its speaker.

    Must return an object satisfying `vision.core.interfaces.Voice`, reading
    settings from `config.voice`. Must not open audio devices or load models
    here; do that in `Voice.start()`. If `start()` raises, the daemon keeps
    running text-only and shows the error as a notice.
    """
    raise NotImplementedError("vision.voice.make_voice is not implemented yet")
