"""The utterance segmenter and the level envelope (no models, no audio devices)."""

from __future__ import annotations

import numpy as np

from vision.voice.audio_io import levels
from vision.voice.vad import FRAME, FRAME_MS, Segmenter, SpeechStarted, Utterance


def feed(seg: Segmenter, probs: list[float]) -> list[SpeechStarted | Utterance]:
    out: list[SpeechStarted | Utterance] = []
    for i, p in enumerate(probs):
        out += seg.push(np.full(FRAME, i, dtype=np.float32), p)
    return out


def ms(n_ms: float) -> int:
    return round(n_ms / FRAME_MS)


def test_silence_of_600_ms_ends_an_utterance() -> None:
    seg = Segmenter(silence_ms=600, preroll_ms=0)
    events = feed(seg, [0.0] * 5 + [0.9] * ms(1000) + [0.1] * (ms(600) - 1))
    assert events == [SpeechStarted()]
    assert seg.in_speech
    events = seg.push(np.zeros(FRAME, dtype=np.float32), 0.1)
    assert len(events) == 1 and isinstance(events[0], Utterance)
    assert events[0].seconds == (ms(1000) + ms(600)) * FRAME / 16_000
    assert not seg.in_speech


def test_short_pauses_do_not_end_an_utterance() -> None:
    seg = Segmenter(silence_ms=600)
    events = feed(seg, [0.9] * 10 + [0.1] * ms(400) + [0.9] * 10 + [0.1] * ms(400))
    assert events == [SpeechStarted()]


def test_hysteresis_keeps_speech_going_between_thresholds() -> None:
    seg = Segmenter(silence_ms=600, threshold=0.5)
    events = feed(seg, [0.9] * 10 + [0.4] * ms(2000))
    assert events == [SpeechStarted()]


def test_maximum_length_cuts_an_utterance() -> None:
    seg = Segmenter(max_s=1.0)
    events = feed(seg, [0.9] * ms(2500))
    utterances = [e for e in events if isinstance(e, Utterance)]
    assert len(utterances) == 2
    assert all(abs(u.seconds - 1.0) < 0.05 for u in utterances)


def test_clicks_end_as_an_empty_utterance() -> None:
    seg = Segmenter(silence_ms=600, min_speech_ms=250)
    events = feed(seg, [0.9] * 2 + [0.0] * ms(700))
    assert events[0] == SpeechStarted()
    assert isinstance(events[1], Utterance) and events[1].audio.size == 0


def test_preroll_keeps_the_start_of_the_word() -> None:
    seg = Segmenter(silence_ms=100, preroll_ms=3 * FRAME_MS)
    events = feed(seg, [0.0] * 10 + [0.9] * 10 + [0.0] * 5)
    utterance = events[-1]
    assert isinstance(utterance, Utterance)
    assert utterance.audio[0] == 7  # frames are numbered; three before speech began


def test_flush_ends_the_utterance_in_progress() -> None:
    seg = Segmenter()
    feed(seg, [0.9] * 20)
    (event,) = seg.flush()
    assert isinstance(event, Utterance) and event.audio.size > 0
    assert seg.flush() == []


def test_levels_envelope() -> None:
    rate = 24_000
    t = np.arange(rate) / rate
    loud = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    env = levels(np.concatenate([loud, np.zeros(rate, dtype=np.float32)]), rate)
    assert len(env) == 60
    assert env[:30].min() > 0.8
    assert env[30:].max() == 0.0
    assert ((env >= 0) & (env <= 1)).all()
