"""The listening pipeline, end to end, with no hardware and no model.

A scripted backend replays synthetic audio through the real capture callback, the
real bounded queue, the real worker thread, the real segmenter and a stub STT
provider. That covers the threading and the state machine integration, which is
where this phase's risk actually lives.
"""

from __future__ import annotations

import asyncio

from bob.audio.devices import AudioDeviceError
from bob.audio.pipeline import ListeningPipeline
from bob.config.loader import load_settings
from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.state_machine import StateMachine
from bob.core.states import BobState
from bob.providers.base import AudioChunk, Transcript, VADDecision

from .audio_fixtures import ScriptedBackend, noise, silence, tone
from .conftest import Recorder


class PatternVAD:
    """Reports speech for frames whose amplitude is above a fixed threshold."""

    def __init__(self, threshold: float = 0.05) -> None:
        self.threshold = threshold
        self.resets = 0

    @property
    def name(self) -> str:
        return "pattern-vad"

    async def start(self) -> None: ...
    async def aclose(self) -> None: ...

    def reset(self) -> None:
        self.resets += 1

    def process(self, frame: AudioChunk) -> VADDecision:
        from bob.audio.frames import rms_level

        level = rms_level(frame.pcm)
        return VADDecision(is_speech=level >= self.threshold, rms=level)


class StubSTT:
    """A stand-in for Whisper: instant, deterministic, no download."""

    def __init__(self, text: str = "Άνοιξε το Spotify", *, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls: list[float] = []

    @property
    def name(self) -> str:
        return "stub-stt"

    async def start(self) -> None: ...
    async def aclose(self) -> None: ...

    async def transcribe(self, audio: AudioChunk, *, language: str | None = None) -> Transcript:
        self.calls.append(audio.duration_s)
        if self.fail:
            raise RuntimeError("stub transcription failure")
        return Transcript(text=self.text, language="el", duration_s=audio.duration_s)


def settings_for(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "vad": {
            "provider": "mock",
            "min_speech_ms": 96,
            "end_silence_ms": 128,
            "pre_roll_ms": 96,
            "max_utterance_s": 5.0,
        },
        "stt": {"provider": "mock"},
        "audio": {"frame_ms": 32.0, "level_update_hz": 120.0, "error_recovery_s": 0.01},
    }
    base.update(overrides)
    return load_settings(overrides=base)


def build(
    bus: EventBus,
    *,
    stt: StubSTT | None = None,
    backend: ScriptedBackend | None = None,
    settings: Settings | None = None,
) -> tuple[ListeningPipeline, StateMachine, StubSTT, ScriptedBackend]:
    machine = StateMachine(bus, initial=BobState.IDLE)
    provider = stt or StubSTT()
    scripted = backend or ScriptedBackend()
    pipeline = ListeningPipeline(
        settings or settings_for(),
        bus,
        machine,
        PatternVAD(),
        provider,  # type: ignore[arg-type]
        scripted,  # type: ignore[arg-type]
    )
    return pipeline, machine, provider, scripted


async def speak(scripted: ScriptedBackend, *, speech_frames: int = 12) -> None:
    """Push silence, then speech, then enough silence to end the utterance."""
    stream = scripted.last_stream
    assert stream is not None
    payloads = (
        [noise()] * 5 + [tone(phase=i * 0.6) for i in range(speech_frames)] + [silence()] * 10
    )
    await asyncio.to_thread(stream.feed, payloads)


async def settle(seconds: float = 1.5) -> None:
    """Give the worker thread and the loop time to finish the round trip.

    Real threads and a real queue are under test, so there is genuinely nothing
    to await on — polling is the honest way to observe them.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.02)


async def wait_for(predicate, limit: float = 3.0) -> bool:  # type: ignore[no-untyped-def]
    """Poll ``predicate`` until it is true or ``limit`` seconds elapse."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


# -- lifecycle --------------------------------------------------------------


async def test_start_listening_opens_the_microphone(bus: EventBus, recorder: Recorder) -> None:
    pipeline, machine, _, scripted = build(bus)
    assert await pipeline.start_listening() is True
    assert machine.state is BobState.LISTENING
    assert scripted.opened == 1
    assert recorder.of("audio.microphone_opened")
    await pipeline.aclose()


async def test_stop_listening_closes_and_returns_to_idle(bus: EventBus, recorder: Recorder) -> None:
    pipeline, machine, _, _backend = build(bus)
    await pipeline.start_listening()
    await pipeline.stop_listening()
    assert machine.state is BobState.IDLE
    assert not pipeline.listening
    assert recorder.of("audio.microphone_closed")
    await pipeline.aclose()


async def test_listening_is_derived_not_a_flag(bus: EventBus) -> None:
    """There is no is_listening boolean; the stream is the truth."""
    pipeline, _, _, _ = build(bus)
    assert not pipeline.listening
    await pipeline.start_listening()
    assert pipeline.listening
    await pipeline.aclose()
    assert not pipeline.listening


async def test_starting_twice_is_harmless(bus: EventBus) -> None:
    pipeline, _, _, scripted = build(bus)
    await pipeline.start_listening()
    await pipeline.start_listening()
    assert scripted.opened == 1
    await pipeline.aclose()


async def test_listening_is_refused_unless_idle(bus: EventBus) -> None:
    """Requirement 8: no parallel listening flow outside the state machine."""
    pipeline, machine, _, scripted = build(bus)
    await machine.transition(BobState.THINKING, reason="test")
    assert await pipeline.start_listening() is False
    assert scripted.opened == 0
    await pipeline.aclose()


async def test_aclose_is_safe_before_listening(bus: EventBus) -> None:
    pipeline, _, _, _ = build(bus)
    await pipeline.aclose()


# -- the full round trip ----------------------------------------------------


async def test_speech_produces_a_transcript(bus: EventBus, recorder: Recorder) -> None:
    pipeline, _machine, stt, scripted = build(bus)
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(lambda: bool(recorder.of("stt.transcript_ready")))

    transcript = recorder.of("stt.transcript_ready")[0]
    assert transcript.text == "Άνοιξε το Spotify"  # type: ignore[attr-defined]
    assert stt.calls, "the STT provider was never called"
    await pipeline.aclose()


async def test_the_documented_state_sequence_is_followed(bus: EventBus, recorder: Recorder) -> None:
    """IDLE -> LISTENING -> TRANSCRIBING -> IDLE, and nothing else."""
    pipeline, machine, _, scripted = build(bus)
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(
        lambda: machine.state is BobState.IDLE and recorder.of("stt.transcript_ready")
    )

    visited = [e.new for e in recorder.of("state.changed")]  # type: ignore[attr-defined]
    assert visited == ["LISTENING", "TRANSCRIBING", "IDLE"]
    await pipeline.aclose()


async def test_speech_events_are_published(bus: EventBus, recorder: Recorder) -> None:
    pipeline, _, _, scripted = build(bus)
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(lambda: bool(recorder.of("stt.transcript_ready")))
    assert recorder.of("audio.speech_started")
    assert recorder.of("audio.speech_ended")
    assert recorder.of("stt.transcription_started")
    await pipeline.aclose()


async def test_audio_levels_reach_the_bus(bus: EventBus, recorder: Recorder) -> None:
    """Requirement 12: the core reacts to the real microphone."""
    pipeline, _, _, scripted = build(bus)
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(lambda: len(recorder.of("audio.level")) > 3)
    levels = [e.rms for e in recorder.of("audio.level")]  # type: ignore[attr-defined]
    assert all(0.0 <= level <= 1.0 for level in levels)
    assert max(levels) > 0.1, "speech should move the meter"
    await pipeline.aclose()


async def test_raw_audio_never_reaches_the_bus(bus: EventBus, recorder: Recorder) -> None:
    """Requirement 9: do not flood the bus with PCM."""
    pipeline, _, _, scripted = build(bus)
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(lambda: bool(recorder.of("stt.transcript_ready")))
    for event in recorder.events:
        assert not hasattr(event, "pcm"), f"{event.type} carries raw audio"
    await pipeline.aclose()


async def test_the_utterance_includes_pre_roll(bus: EventBus, recorder: Recorder) -> None:
    pipeline, _, stt, scripted = build(bus)
    await pipeline.start_listening()
    await speak(scripted, speech_frames=12)
    assert await wait_for(lambda: bool(stt.calls))
    speech_only = 12 * 0.032
    assert stt.calls[0] > speech_only, "pre-roll was not prepended"
    await pipeline.aclose()


async def test_repeated_utterances_work_without_restarting(
    bus: EventBus, recorder: Recorder
) -> None:
    """Acceptance criterion 9: repeat many times without restarting the app."""
    pipeline, machine, stt, scripted = build(bus)
    for round_index in range(3):
        await pipeline.start_listening()
        await speak(scripted)
        assert await wait_for(lambda n=round_index: len(recorder.of("stt.transcript_ready")) > n), (
            f"round {round_index} produced no transcript"
        )
        assert machine.state is BobState.IDLE
    assert len(stt.calls) == 3
    await pipeline.aclose()


async def test_silence_alone_produces_no_transcript(bus: EventBus, recorder: Recorder) -> None:
    """Requirement 5: never send endless silence to the STT model."""
    pipeline, _, stt, scripted = build(bus)
    await pipeline.start_listening()
    stream = scripted.last_stream
    assert stream is not None
    await asyncio.to_thread(stream.feed, [noise()] * 40)
    await settle(0.6)
    assert stt.calls == []
    assert recorder.of("stt.transcript_ready") == []
    await pipeline.aclose()


async def test_a_brief_noise_is_not_transcribed(bus: EventBus) -> None:
    pipeline, _, stt, scripted = build(bus)
    await pipeline.start_listening()
    stream = scripted.last_stream
    assert stream is not None
    await asyncio.to_thread(stream.feed, [noise()] * 5 + [tone()] * 1 + [silence()] * 12)
    await settle(0.6)
    assert stt.calls == []
    await pipeline.aclose()


# -- errors and recovery ----------------------------------------------------


async def test_missing_microphone_is_reported_not_fatal(bus: EventBus, recorder: Recorder) -> None:
    pipeline, machine, _, _unused = build(bus, backend=ScriptedBackend(devices=[]))
    assert await pipeline.start_listening() is False
    assert recorder.of("audio.device_error")
    assert await wait_for(lambda: machine.state is BobState.IDLE)
    await pipeline.aclose()


async def test_device_open_failure_recovers_to_idle(bus: EventBus, recorder: Recorder) -> None:
    backend = ScriptedBackend(fail_with=AudioDeviceError("Windows refused access"))
    pipeline, machine, _, _ = build(bus, backend=backend)
    assert await pipeline.start_listening() is False
    error = recorder.of("audio.device_error")[0]
    assert "refused" in error.message  # type: ignore[attr-defined]
    assert await wait_for(lambda: machine.state is BobState.IDLE)
    await pipeline.aclose()


async def test_transcription_failure_recovers_to_idle(bus: EventBus, recorder: Recorder) -> None:
    """A failed transcription must not require restarting B.O.B."""
    pipeline, machine, _, scripted = build(bus, stt=StubSTT(fail=True))
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(lambda: bool(recorder.of("stt.transcription_failed")))
    assert await wait_for(lambda: machine.state is BobState.IDLE)
    assert pipeline.stats().transcription_failures == 1
    await pipeline.aclose()


async def test_b_o_b_still_listens_after_a_failure(bus: EventBus, recorder: Recorder) -> None:
    stt = StubSTT(fail=True)
    pipeline, machine, _, scripted = build(bus, stt=stt)
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(lambda: machine.state is BobState.IDLE and stt.calls)

    stt.fail = False
    assert await pipeline.start_listening() is True
    await speak(scripted)
    assert await wait_for(lambda: bool(recorder.of("stt.transcript_ready")))
    await pipeline.aclose()


async def test_empty_transcript_returns_to_idle_quietly(bus: EventBus, recorder: Recorder) -> None:
    pipeline, machine, _, scripted = build(bus, stt=StubSTT(text="   "))
    await pipeline.start_listening()
    await speak(scripted)
    assert await wait_for(lambda: machine.state is BobState.IDLE)
    assert recorder.of("stt.transcript_ready") == []
    await pipeline.aclose()


# -- backpressure -----------------------------------------------------------


async def test_the_queue_is_bounded(bus: EventBus) -> None:
    """Requirement 6: explicit bounded buffering, never unbounded growth."""
    pipeline, _, _, _ = build(bus)
    assert pipeline._queue.capacity > 0
    assert pipeline._queue.capacity < 500
    await pipeline.aclose()


async def test_a_flood_of_audio_drops_frames_rather_than_growing(bus: EventBus) -> None:
    pipeline, _, _, scripted = build(bus)
    await pipeline.start_listening()
    stream = scripted.last_stream
    assert stream is not None
    # Far more frames than the queue holds, delivered as fast as possible.
    await asyncio.to_thread(stream.feed, [tone()] * 4000)
    stats = pipeline.stats()
    assert len(pipeline._queue) <= pipeline._queue.capacity
    assert stats.queue.high_water <= pipeline._queue.capacity
    await pipeline.aclose()


async def test_stats_are_reported(bus: EventBus) -> None:
    pipeline, _, _, scripted = build(bus)
    await pipeline.start_listening()
    await speak(scripted)
    await settle(0.5)
    stats = pipeline.stats()
    assert stats.frames_processed > 0
    assert stats.queue.pushed > 0
    await pipeline.aclose()


# -- device listing ---------------------------------------------------------


def test_devices_are_listed_through_the_pipeline(bus: EventBus) -> None:
    pipeline, _, _, _ = build(bus)
    assert [d.name for d in pipeline.list_devices()] == ["Test Microphone"]


def test_device_enumeration_failure_is_not_fatal(bus: EventBus) -> None:
    backend = ScriptedBackend(devices=[], fail_with=AudioDeviceError("no audio stack"))
    pipeline, _, _, _ = build(bus, backend=backend)
    assert pipeline.list_devices() == []
