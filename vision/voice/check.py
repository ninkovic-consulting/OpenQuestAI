"""Try the microphone and speakers: `python -m vision.voice.check`.

Lists the audio devices, records a few seconds, prints what Whisper heard and
says it back. Uses the devices and models from `[voice]` in config.toml.
The models must be downloaded first (Settings, Voice, or `vision setup`).
"""

from __future__ import annotations

import argparse
import asyncio
import time

import numpy as np

from vision.core.bus import Bus
from vision.core.config import load_config
from vision.voice.audio_io import Microphone, SpeakerOutput, describe_devices
from vision.voice.errors import VoiceUnavailable
from vision.voice.settings import VoiceSettings
from vision.voice.stt import WhisperStt
from vision.voice.tts import TtsSpeaker, load_synth
from vision.voice.vad import SAMPLE_RATE
from vision.voice.worker import Worker


async def _record(mic: Microphone, seconds: float) -> np.ndarray:
    chunks: list[np.ndarray] = []
    wanted = int(seconds * SAMPLE_RATE)
    async for chunk in mic.chunks():
        chunks.append(chunk)
        if sum(len(c) for c in chunks) >= wanted:
            break
    return np.concatenate(chunks)[:wanted]


async def check(seconds: float) -> None:
    settings = VoiceSettings.from_config(load_config())
    print("Audio devices (> is the default input, < the default output):")
    print(describe_devices())

    worker = Worker()
    try:
        started = time.perf_counter()
        stt = WhisperStt(settings.stt_model)
        await worker.run(stt.load)
        synth, degraded = await worker.run(lambda: load_synth(settings))
        if degraded:
            print(degraded)
        print(f"\nModels ready in {time.perf_counter() - started:.1f} s "
              f"({settings.stt_model}, {type(synth).__name__}).")

        mic = Microphone(settings.input_device, on_missing=print)
        await mic.open()
        print(f"Recording {seconds:g} seconds from {mic.name}. Say something...")
        try:
            audio = await _record(mic, seconds)
        finally:
            await mic.close()

        started = time.perf_counter()
        text = await worker.run(lambda: stt.transcribe(audio))
        print(f"Heard ({time.perf_counter() - started:.2f} s): {text or '(nothing)'}")

        sink = SpeakerOutput(settings.output_device, on_missing=print)
        sink.open()
        speaker = TtsSpeaker(Bus(), sink, worker.run)
        speaker.use(synth)
        await speaker.say(f"I heard: {text}" if text else "I did not hear anything.")
    finally:
        worker.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=3.0, help="how long to record")
    args = parser.parse_args()
    try:
        asyncio.run(check(args.seconds))
    except VoiceUnavailable as exc:
        raise SystemExit(f"Voice is unavailable: {exc}") from None


if __name__ == "__main__":
    main()
