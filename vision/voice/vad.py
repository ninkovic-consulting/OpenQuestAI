"""Voice activity detection: Silero VAD (on MLX) and the utterance segmenter.

`SileroVad` turns each 32 ms frame (512 samples at 16 kHz) into a speech
probability. `Segmenter` turns that stream of probabilities into utterances:
speech starts when the probability crosses `threshold`, and the utterance ends
after `silence_ms` below `threshold - 0.15`, or when it reaches `max_s`.
Bursts shorter than `min_speech_ms` (clicks, coughs) end as an empty
`Utterance`, so the listener can step back to idle. A little audio from
before the start is kept so the first syllable is not clipped.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from vision.voice.on_disk import local_path
from vision.voice.settings import VAD_PART

SAMPLE_RATE = 16_000
FRAME = 512
FRAME_MS = 1000 * FRAME / SAMPLE_RATE


class SpeechDetector(Protocol):
    def probability(self, frame: np.ndarray) -> float:
        """Speech probability for one `FRAME`-sample float32 frame."""
        ...

    def reset(self) -> None:
        """Forget the stream so far."""
        ...


class SileroVad:
    """Silero VAD v5 running on MLX through `mlx-audio`. Load with `load()`, from the disk only."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self._model: Any = None
        self._state: Any = None

    def load(self) -> None:
        from mlx_audio.vad import load

        self._model = load(str(local_path(self.repo, VAD_PART)))
        self.reset()

    def reset(self) -> None:
        self._state = self._model.initial_state(sample_rate=SAMPLE_RATE)

    def probability(self, frame: np.ndarray) -> float:
        import mlx.core as mx

        prob, self._state = self._model.feed(frame, self._state, sample_rate=SAMPLE_RATE)
        mx.eval(prob)
        return float(np.asarray(prob).reshape(-1)[0])


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    pass


@dataclass(frozen=True, slots=True)
class Utterance:
    audio: np.ndarray
    """16 kHz mono float32."""

    @property
    def seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE


SegmentEvent = SpeechStarted | Utterance


class Segmenter:
    """Cuts a stream of (frame, probability) pairs into utterances."""

    def __init__(
        self,
        *,
        silence_ms: int = 600,
        max_s: float = 15.0,
        threshold: float = 0.5,
        min_speech_ms: int = 250,
        preroll_ms: int = 300,
    ) -> None:
        self.threshold = threshold
        self.release = max(0.0, threshold - 0.15)
        self._silence_frames = max(1, round(silence_ms / FRAME_MS))
        self._max_frames = max(1, round(max_s * 1000 / FRAME_MS))
        self._min_speech_frames = max(1, round(min_speech_ms / FRAME_MS))
        self._preroll: deque[np.ndarray] = deque(maxlen=max(0, round(preroll_ms / FRAME_MS)))
        self._frames: list[np.ndarray] = []
        self._speech_frames = 0
        self._quiet = 0

    @property
    def in_speech(self) -> bool:
        return bool(self._frames)

    def push(self, frame: np.ndarray, prob: float) -> list[SegmentEvent]:
        if not self._frames:
            if prob < self.threshold:
                self._preroll.append(frame)
                return []
            self._frames = [*self._preroll, frame]
            self._preroll.clear()
            self._speech_frames = 1
            self._quiet = 0
            return [SpeechStarted()]
        self._frames.append(frame)
        if prob >= self.release:
            self._speech_frames += 1
            self._quiet = 0
        else:
            self._quiet += 1
        if self._quiet >= self._silence_frames or len(self._frames) >= self._max_frames:
            return self._close()
        return []

    def flush(self) -> list[SegmentEvent]:
        """End the utterance in progress, if any (the input ended)."""
        return self._close() if self._frames else []

    def _close(self) -> list[SegmentEvent]:
        frames, speech = self._frames, self._speech_frames
        self._frames, self._speech_frames, self._quiet = [], 0, 0
        if speech < self._min_speech_frames:
            return [Utterance(np.zeros(0, dtype=np.float32))]
        return [Utterance(np.concatenate(frames).astype(np.float32, copy=False))]
