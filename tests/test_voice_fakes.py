"""Model stand-ins for the voice tests (no tests here): a tone for speech, loudness for VAD, a script for STT."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

import numpy as np

from vision.core.bus import Subscription
from vision.core.events import Event

T = TypeVar("T")


class ToneSynth:
    """Every sentence is a tone of `seconds`. Records what it was asked to say."""

    sample_rate = 24_000

    def __init__(self, seconds: float = 0.3) -> None:
        self.seconds = seconds
        self.texts: list[str] = []

    def load(self) -> None:
        pass

    def synth(self, text: str) -> np.ndarray:
        self.texts.append(text)
        t = np.arange(int(self.seconds * self.sample_rate)) / self.sample_rate
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class LoudnessVad:
    """Speech is anything louder than 0.1."""

    def load(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def probability(self, frame: np.ndarray) -> float:
        return 1.0 if float(np.abs(frame).max()) > 0.1 else 0.0


class ScriptedStt:
    """Returns the scripted transcripts in order, then ""."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.heard: list[float] = []

    def load(self) -> None:
        pass

    def transcribe(self, audio: np.ndarray) -> str:
        self.heard.append(len(audio) / 16_000)
        return self.texts.pop(0) if self.texts else ""


async def run_now(fn: Callable[[], T]) -> T:
    return fn()


async def drain(sub: Subscription, wait: float = 0.01) -> list[Event]:
    out: list[Event] = []
    while True:
        try:
            out.append(await asyncio.wait_for(sub.get(), wait))
        except TimeoutError:
            return out
