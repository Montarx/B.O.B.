"""Provider contracts.

Mocks are checked against the same Protocols the real providers must satisfy, so a
Phase 2/3/4 implementation that drifts from the interface fails here first.
"""

from __future__ import annotations

import pytest

from bob.core.errors import ProviderNotFoundError
from bob.providers import registry
from bob.providers.base import (
    AudioChunk,
    LLMProvider,
    MemoryProvider,
    Message,
    STTProvider,
    TTSProvider,
    VADProvider,
    VisionProvider,
    WakeWordProvider,
)
from bob.providers.mock.llm import MockLLM
from bob.providers.mock.memory import MockMemory
from bob.providers.mock.stt import MockSTT
from bob.providers.mock.tts import MockTTS
from bob.providers.mock.vad import MockVAD
from bob.providers.mock.vision import MockVision
from bob.providers.mock.wakeword import MockWakeWord


@pytest.mark.parametrize(
    ("impl", "protocol"),
    [
        (MockLLM(), LLMProvider),
        (MockSTT(), STTProvider),
        (MockTTS(), TTSProvider),
        (MockVAD(), VADProvider),
        (MockWakeWord(), WakeWordProvider),
        (MockMemory(), MemoryProvider),
        (MockVision(), VisionProvider),
    ],
)
def test_mock_satisfies_its_protocol(impl: object, protocol: type) -> None:
    assert isinstance(impl, protocol)


def test_every_kind_has_a_mock_registered() -> None:
    for kind in ("llm", "stt", "tts", "vad", "wakeword", "memory", "vision"):
        assert "mock" in registry.available(kind)  # type: ignore[arg-type]


def test_unknown_provider_names_are_reported_clearly() -> None:
    with pytest.raises(ProviderNotFoundError, match="available"):
        registry.create("llm", "gpt-9000")


async def test_llm_streams_chunks_and_terminates() -> None:
    llm = MockLLM(scripted=["Ναι ρε, ένα δευτερόλεπτο."])
    chunks = [c async for c in llm.generate([Message("user", "άνοιξε spotify")])]
    assert chunks[-1].done
    text = "".join(c.text for c in chunks).strip()
    assert text == "Ναι ρε, ένα δευτερόλεπτο."


async def test_tts_streams_multiple_chunks() -> None:
    """Chunked output is what makes barge-in possible."""
    tts = MockTTS(chars_per_chunk=4)
    chunks = [c async for c in tts.synthesize("μια δοκιμή για τον Μπομπ")]
    assert len(chunks) > 1
    assert all(c.sample_rate > 0 for c in chunks)


async def test_tts_stream_can_be_abandoned_midway() -> None:
    """The user interrupts: we stop consuming and nothing breaks."""
    tts = MockTTS(chars_per_chunk=2)
    stream = tts.synthesize("ένα μεγάλο κείμενο που κόβεται στη μέση")
    first = await anext(stream)
    await stream.aclose()
    assert first.pcm


async def test_stt_returns_queued_transcript() -> None:
    stt = MockSTT(scripted=["άνοιξε το spotify"])
    result = await stt.transcribe(AudioChunk(pcm=b"\x00\x00" * 1600, sample_rate=16000))
    assert result.text == "άνοιξε το spotify"
    assert not result.is_empty


def test_vad_distinguishes_silence_from_signal() -> None:
    vad = MockVAD(threshold=100.0)
    silence = AudioChunk(pcm=b"\x00\x00" * 320, sample_rate=16000)
    loud = AudioChunk(pcm=b"\xff\x7f" * 320, sample_rate=16000)
    assert not vad.process(silence).is_speech
    assert vad.process(loud).is_speech


def test_wake_word_only_fires_when_triggered() -> None:
    wake = MockWakeWord(keyword="μπομπ")
    frame = AudioChunk(pcm=b"\x00\x00" * 320, sample_rate=16000)
    assert wake.process(frame) is None
    wake.trigger()
    detection = wake.process(frame)
    assert detection is not None and detection.keyword == "μπομπ"
    assert wake.process(frame) is None  # single-shot


async def test_memory_is_deliberate_inspectable_and_deletable() -> None:
    memory = MockMemory()
    record = await memory.remember("Προτιμάει καφέ χωρίς ζάχαρη", kind="preference")

    assert await memory.recall("καφέ")
    assert [r.id for r in await memory.list_all()] == [record.id]

    assert await memory.forget(record.id) is True
    assert await memory.list_all() == []
    assert await memory.forget(record.id) is False


async def test_vision_is_only_called_explicitly() -> None:
    vision = MockVision()
    assert vision.calls == []
    await vision.describe(b"\x89PNG fake", prompt="τι βλέπεις;")
    assert len(vision.calls) == 1


def test_audio_chunk_duration_is_computed_from_the_format() -> None:
    chunk = AudioChunk(pcm=b"\x00\x00" * 16_000, sample_rate=16_000)
    assert chunk.duration_s == pytest.approx(1.0)
