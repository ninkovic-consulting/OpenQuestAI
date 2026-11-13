"""Speech models load from the disk only and are never fetched by themselves.

`huggingface_hub` and `mlx-audio` are faked, so nothing here reaches the network
or the real Hugging Face cache (HF_HUB_CACHE points at a temporary folder).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from vision.voice import on_disk, tts
from vision.voice.on_disk import ModelMissing, local_path, require
from vision.voice.service import default_models
from vision.voice.settings import STT_PART, TAGGER_PART, TTS_PART, VoiceSettings
from vision.voice.stt import WhisperStt
from vision.voice.vad import SileroVad

SETTINGS = VoiceSettings(name="Vision")


class FakeHub(types.ModuleType):
    """`huggingface_hub` that reads a pretend cache and fails any call that could fetch."""

    def __init__(self, cached: dict[str, Path]) -> None:
        super().__init__("huggingface_hub")
        self.cached = cached
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def snapshot_download(self, repo: str, **kw: Any) -> str:
        self.calls.append((repo, kw))
        if not kw.get("local_files_only"):
            raise AssertionError("a speech model was about to be fetched")
        if repo not in self.cached:
            raise FileNotFoundError(f"{repo} is not in the cache")  # as LocalEntryNotFoundError
        return str(self.cached[repo])


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeHub:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    fake = FakeHub({})
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    return fake


def cache(tmp_path: Path, repo: str) -> Path:
    """Put a snapshot of `repo` in the temporary cache, as a finished download leaves it."""
    snapshot = tmp_path / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    return snapshot


def test_a_cached_model_loads_from_its_folder_without_the_network(hub: FakeHub, tmp_path: Path) -> None:
    folder = cache(tmp_path, SETTINGS.stt_model)
    assert local_path(SETTINGS.stt_model, STT_PART) == folder
    assert hub.calls == []  # found on disk; the Hub's own lookup refuses partial snapshots


def test_a_missing_model_fails_with_where_to_download_it(hub: FakeHub) -> None:
    with pytest.raises(ModelMissing) as caught:
        local_path(SETTINGS.tts_model, TTS_PART)
    assert str(caught.value) == (
        "The speech models are not downloaded (the speaking voice missing). "
        "Download them in Settings, Voice; nothing is downloaded by itself."
    )


def test_starting_voice_names_every_missing_part_before_loading_any(
    hub: FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache(tmp_path, SETTINGS.vad_model)
    cache(tmp_path, SETTINGS.stt_model)
    loaded: list[str] = []
    monkeypatch.setattr(SileroVad, "load", lambda self: loaded.append("vad"))
    monkeypatch.setattr(WhisperStt, "load", lambda self: loaded.append("stt"))
    with pytest.raises(ModelMissing) as caught:
        default_models(SETTINGS)()
    assert f"({TTS_PART}, {TAGGER_PART} missing)" in str(caught.value)
    assert loaded == [] and hub.calls == []


def test_require_passes_when_everything_is_downloaded(hub: FakeHub, tmp_path: Path) -> None:
    for repo in SETTINGS.model_repos():
        cache(tmp_path, repo)
    require(SETTINGS.parts())
    assert on_disk.missing(SETTINGS.speech_parts()) == []


def test_whisper_is_handed_the_local_folder(
    hub: FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = cache(tmp_path, SETTINGS.stt_model)
    hub.cached[SETTINGS.stt_model] = folder
    given: list[str] = []

    class Model:
        def generate(self, audio: np.ndarray, **kw: Any) -> Any:
            return types.SimpleNamespace(text="")

    def load(path: str) -> Model:
        given.append(path)
        return Model()

    utils = types.ModuleType("mlx_audio.stt.utils")
    utils.load = load  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_audio.stt.utils", utils)
    WhisperStt(SETTINGS.stt_model).load()
    assert given == [str(folder)]


def test_kokoro_and_its_tagger_never_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mlx_audio")
    asked: list[str] = []

    def missing(repo: str, part: str) -> Path:
        asked.append(repo)
        raise ModelMissing(on_disk.missing_message([part]))

    monkeypatch.setattr(tts, "local_path", missing)
    with pytest.raises(ModelMissing):
        tts.KokoroSynth(SETTINGS.tts_model, "af_heart").load()
    pytest.importorskip("misaki")
    with pytest.raises(ModelMissing):
        tts._english_g2p()
    assert asked == [SETTINGS.tts_model, "spacy/en_core_web_sm"]
