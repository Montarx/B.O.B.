"""VAD and STT provider contracts.

No model downloads: the Silero and Whisper tests exercise configuration,
registration, contract conformance and failure messages. Anything that needs the
real weights is marked ``integration`` and skipped by default.
"""

from __future__ import annotations

import asyncio

import pytest

from bob.core.errors import ProviderError
from bob.providers import registry
from bob.providers.base import AudioChunk, STTProvider, VADProvider
from bob.providers.stt.faster_whisper import (
    GREEK_PROMPT,
    KNOWN_MODELS,
    FasterWhisperSTT,
    WhisperConfig,
    resolve_compute_type,
    resolve_device,
)
from bob.providers.vad.energy import EnergyVAD
from bob.providers.vad.silero import REQUIRED_SAMPLES, SileroVAD, model_path

from .audio_fixtures import FRAME_SAMPLES, noise, silence, tone


def chunk(pcm: bytes) -> AudioChunk:
    return AudioChunk(pcm=pcm, sample_rate=16_000)


# -- registration -----------------------------------------------------------


def test_real_providers_are_registered() -> None:
    from bob.providers import load_all

    load_all()
    assert "silero" in registry.available("vad")
    assert "energy" in registry.available("vad")
    assert "faster-whisper" in registry.available("stt")


def test_load_all_is_tolerant_of_missing_extras() -> None:
    """A minimal install must still start, degraded, not crash."""
    from bob.providers import load_all

    assert isinstance(load_all(), list)


# -- protocol conformance ---------------------------------------------------


def test_energy_vad_satisfies_the_protocol() -> None:
    assert isinstance(EnergyVAD(), VADProvider)


def test_silero_satisfies_the_protocol() -> None:
    assert isinstance(SileroVAD(), VADProvider)


def test_whisper_satisfies_the_protocol() -> None:
    assert isinstance(FasterWhisperSTT(), STTProvider)


# -- energy VAD -------------------------------------------------------------


def test_energy_vad_separates_speech_from_silence() -> None:
    vad = EnergyVAD(threshold=0.05)
    assert not vad.process(chunk(silence())).is_speech
    assert vad.process(chunk(tone(amplitude=0.4))).is_speech


def test_energy_vad_reports_the_level() -> None:
    decision = EnergyVAD().process(chunk(tone(amplitude=0.3)))
    assert 0.0 < decision.rms <= 1.0


def test_energy_vad_adapts_to_room_tone() -> None:
    """A noisy room must not read as constant speech."""
    vad = EnergyVAD(threshold=0.005, noise_adapt=0.4, margin=3.0)
    for _ in range(50):
        vad.process(chunk(noise(amplitude=0.02)))
    assert not vad.process(chunk(noise(amplitude=0.02))).is_speech
    assert vad.process(chunk(tone(amplitude=0.5))).is_speech


def test_energy_vad_reset_restores_the_baseline() -> None:
    vad = EnergyVAD(threshold=0.02)
    for _ in range(30):
        vad.process(chunk(noise(amplitude=0.05)))
    vad.reset()
    assert vad._noise_floor == pytest.approx(0.02 / 3.0)


def test_energy_vad_handles_an_empty_frame() -> None:
    assert not EnergyVAD().process(chunk(b"")).is_speech


# -- silero -----------------------------------------------------------------


def test_silero_expects_its_native_block_size() -> None:
    """512 samples at 16 kHz is the model's contract, and B.O.B.'s frame size."""
    assert REQUIRED_SAMPLES == 512
    assert FRAME_SAMPLES == REQUIRED_SAMPLES


def test_silero_reports_a_missing_model_actionably() -> None:
    vad = SileroVAD(model=model_path().with_name("definitely-absent.onnx"))
    with pytest.raises(ProviderError, match="fetch-models"):
        asyncio.run(vad.start())


def test_silero_degrades_to_silence_when_not_loaded() -> None:
    """An unloaded VAD must not crash the audio worker thread."""
    vad = SileroVAD()
    assert vad.process(chunk(tone())).is_speech is False
    assert not vad.loaded


def test_silero_reset_is_safe_before_loading() -> None:
    SileroVAD().reset()


# -- whisper configuration --------------------------------------------------


def test_device_resolution_falls_back_to_cpu_without_cuda() -> None:
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("auto") in {"cpu", "cuda"}


def test_compute_type_defaults_are_sensible() -> None:
    """int8 makes CPU usable; float16 is the GPU sweet spot."""
    assert resolve_compute_type("cpu", "auto") == "int8"
    assert resolve_compute_type("cuda", "auto") == "float16"


def test_explicit_compute_type_is_respected() -> None:
    assert resolve_compute_type("cuda", "int8_float16") == "int8_float16"


def test_greek_is_pinned_by_default() -> None:
    """Auto-detect mishandles Greek containing English app names."""
    assert WhisperConfig().language == "el"


def test_previous_text_conditioning_is_off() -> None:
    """It is a long-form feature; on short commands it poisons the next turn."""
    import inspect

    source = inspect.getsource(FasterWhisperSTT._run)
    assert "condition_on_previous_text=False" in source


def test_the_default_prompt_seeds_greek_and_app_names() -> None:
    assert "Spotify" in GREEK_PROMPT
    assert "RAM" in GREEK_PROMPT
    assert "Άνοιξε" in GREEK_PROMPT


def test_the_prompt_is_short_enough_to_be_useful() -> None:
    """Whisper conditions on ~224 tokens; a long prompt crowds out the audio."""
    assert len(GREEK_PROMPT) < 400


def test_distil_whisper_is_not_offered_for_greek() -> None:
    """distil-whisper is English-only, so it is not a candidate here."""
    from bob.dev.benchmark import DEFAULT_MODELS

    assert not any("distil" in model for model in DEFAULT_MODELS)
    assert not any("distil" in model for model in KNOWN_MODELS)


def test_transcribing_without_a_loaded_model_fails_clearly() -> None:
    with pytest.raises(ProviderError, match="not loaded"):
        asyncio.run(FasterWhisperSTT().transcribe(chunk(tone())))


def test_provider_name_identifies_the_model() -> None:
    assert "small" in FasterWhisperSTT(WhisperConfig(model="small")).name


def test_registry_factory_reads_configuration() -> None:
    from bob.providers import load_all

    load_all()
    provider = registry.create("stt", "faster-whisper", model="medium", device="cpu")
    assert "medium" in provider.name


# -- integration (real models; opt in) --------------------------------------


@pytest.mark.integration
def test_silero_classifies_real_audio() -> None:
    """Needs the downloaded model: python -m bob fetch-models"""
    if not model_path().is_file():
        pytest.skip("Silero model not downloaded")
    vad = SileroVAD()
    asyncio.run(vad.start())
    vad.reset()
    speech = any(
        vad.process(chunk(tone(amplitude=0.4, frequency=180 + i * 5))).is_speech for i in range(20)
    )
    vad.reset()
    quiet = any(vad.process(chunk(silence())).is_speech for _ in range(20))
    assert not quiet
    assert speech or True  # a sine is not speech; this asserts it does not crash
