"""Speech recognition: Whisper on MLX through `mlx-audio`, English only.

The default model is `mlx-community/whisper-large-v3-turbo-asr-fp16`: large-v3 accuracy
with a 4-layer decoder, which keeps a short utterance well under a second on
Apple Silicon. Load once with `load()`; call `transcribe()` off the event loop.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> str:
        """Text for 16 kHz mono float32 audio ("" for none). Blocking."""
        ...


class WhisperStt:
    def __init__(self, repo: str) -> None:
        self.repo = repo
        self._model: Any = None

    def load(self) -> None:
        from mlx_audio.stt.utils import load

        self._model = load(self.repo)
        self.transcribe(np.zeros(16_000, dtype=np.float32))  # compile the kernels once

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
        result = self._model.generate(
            audio.astype(np.float32, copy=False),
            language="en",
            temperature=0.0,
            condition_on_previous_text=False,
            verbose=None,
        )
        return str(result.text).strip()
