"""The listening pipeline.

Wires capture, VAD, segmentation and transcription to the kernel's event bus and
state machine.

**Concurrency**, which is the whole design::

    PortAudio callback thread  ── push ──▶  FrameQueue (bounded, drops oldest)
                                                 │
    Audio worker thread  ──── pop ───────────────┘
        VAD  →  Segmenter  →  LevelMeter
        on utterance:  loop.call_soon_threadsafe(...)
                                                 │
    Kernel asyncio loop  ◀───────────────────────┘
        state machine, event bus
        transcription via run_in_executor  →  STT worker thread

Three threads plus an executor, with exactly one hand-off mechanism between each
pair. Nothing here touches Qt, and no step can block the GUI thread.

The state machine is the only record of what B.O.B. is doing — there is no
``is_listening`` flag in this module, by design.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from dataclasses import dataclass

from bob.audio.capture import frame_samples_for
from bob.audio.devices import (
    AudioBackend,
    AudioDevice,
    AudioDeviceError,
    StreamHandle,
    describe_devices,
    select_device,
)
from bob.audio.frames import (
    AudioFrame,
    FrameQueue,
    QueueStats,
    Utterance,
)
from bob.audio.levels import LevelConfig, LevelMeter
from bob.audio.segmenter import (
    SegmentationConfig,
    Segmenter,
    SpeechBegan,
    SpeechDiscarded,
    SpeechEnded,
)
from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.events import (
    AudioDeviceErrorEvent,
    AudioLevel,
    MicrophoneClosed,
    MicrophoneOpened,
    SpeechStarted,
    TranscriptionFailed,
    TranscriptionStarted,
    TranscriptPartial,
    TranscriptReady,
)
from bob.core.events import (
    SpeechEnded as SpeechEndedEvent,
)
from bob.core.state_machine import StateMachine
from bob.core.states import BobState
from bob.providers.base import AudioChunk, STTProvider, VADProvider

_log = logging.getLogger("bob.app.audio.pipeline")

#: How long the worker waits for a frame before re-checking whether to stop.
_POLL_TIMEOUT_S = 0.25


@dataclass(frozen=True, slots=True)
class PipelineStats:
    """Snapshot for diagnostics and the UI."""

    queue: QueueStats
    frames_processed: int
    utterances: int
    discarded: int
    transcription_failures: int
    listening: bool


class ListeningPipeline:
    """Owns microphone capture and turns speech into transcripts."""

    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        state: StateMachine,
        vad: VADProvider,
        stt: STTProvider,
        backend: AudioBackend,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._state = state
        self._vad = vad
        self._stt = stt
        self._backend = backend
        self._loop = loop

        audio = settings.audio
        self._frame_samples = frame_samples_for(audio.sample_rate, audio.frame_ms)
        self._frame_ms = audio.frame_ms

        # Bound the queue by time, not by an arbitrary frame count: two seconds
        # of audio is plenty of slack for a scheduling hiccup, and small enough
        # that a wedged consumer is noticed rather than silently buffering.
        capacity = max(8, int(2000 / max(1.0, audio.frame_ms)))
        self._queue = FrameQueue(capacity)

        self._segmenter = Segmenter(
            SegmentationConfig(
                min_speech_ms=settings.vad.min_speech_ms,
                end_silence_ms=settings.vad.end_silence_ms,
                pre_roll_ms=settings.vad.pre_roll_ms,
                max_utterance_s=settings.vad.max_utterance_s,
            ),
            frame_ms=audio.frame_ms,
            sample_rate=audio.sample_rate,
        )
        self._meter = LevelMeter(LevelConfig(update_hz=audio.level_update_hz))

        self._stream: StreamHandle | None = None
        self._device: AudioDevice | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._sequence = 0
        self._frames_processed = 0
        self._utterances = 0
        self._discarded = 0
        self._failures = 0
        self._transcribing: asyncio.Task[None] | None = None

    # -- introspection ---------------------------------------------------

    @property
    def listening(self) -> bool:
        """Capture is running. Derived, not a flag the pipeline sets itself."""
        return self._stream is not None and self._stream.active

    @property
    def device(self) -> AudioDevice | None:
        return self._device

    def stats(self) -> PipelineStats:
        return PipelineStats(
            queue=self._queue.stats,
            frames_processed=self._frames_processed,
            utterances=self._utterances,
            discarded=self._discarded,
            transcription_failures=self._failures,
            listening=self.listening,
        )

    def list_devices(self) -> list[AudioDevice]:
        try:
            return self._backend.list_input_devices()
        except AudioDeviceError:
            _log.exception("device enumeration failed")
            return []

    def describe_devices(self) -> str:
        return describe_devices(self.list_devices())

    # -- lifecycle -------------------------------------------------------

    async def start_listening(self) -> bool:
        """Open the microphone and move to LISTENING.

        Returns ``False`` and reports the reason on the bus if the device cannot
        be opened; B.O.B. stays usable rather than crashing.
        """
        if self.listening:
            return True
        if self._state.state is not BobState.IDLE:
            _log.info("ignoring listen request while %s", self._state.state)
            return False

        self._loop = self._loop or asyncio.get_running_loop()

        try:
            devices = self._backend.list_input_devices()
            if not devices:
                raise AudioDeviceError("no microphone found. Connect one and try again.")
            device = select_device(devices, self._settings.audio.input_device)
            stream = self._backend.open_stream(
                device,
                sample_rate=self._settings.audio.sample_rate,
                frame_samples=self._frame_samples,
                callback=self._on_audio,
            )
        except AudioDeviceError as exc:
            await self._fail_device(str(exc))
            return False
        except Exception as exc:
            await self._fail_device(f"unexpected audio error: {exc}")
            return False

        self._stream = stream
        self._device = device
        self._reset_for_utterance()
        self._queue.reopen()
        self._stop.clear()

        self._worker = threading.Thread(target=self._run_worker, name="bob-audio", daemon=True)
        self._worker.start()

        await self._state.transition(BobState.LISTENING, reason="listen requested")
        await self._bus.publish(
            MicrophoneOpened(
                source="audio",
                device=device.label if device else "default",
                sample_rate=self._settings.audio.sample_rate,
            )
        )
        return True

    async def stop_listening(self, *, reason: str = "user") -> None:
        """Close the microphone and return to IDLE."""
        self._close_stream()
        if self._state.state is BobState.LISTENING:
            await self._state.transition(BobState.IDLE, reason=reason)
        await self._bus.publish(MicrophoneClosed(source="audio", reason=reason))

    async def aclose(self) -> None:
        """Shut everything down. Safe whether or not listening was ever started."""
        self._close_stream()
        if self._transcribing is not None and not self._transcribing.done():
            self._transcribing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._transcribing

    def _close_stream(self) -> None:
        self._stop.set()
        self._queue.close()
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        worker, self._worker = self._worker, None
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        # Reuse the queue rather than replacing it, so cumulative drop counts
        # survive across listening sessions.
        self._queue.reopen()

    # -- the audio callback (PortAudio realtime thread) ------------------

    def _on_audio(self, pcm: bytes, timestamp: float) -> None:
        """Runs on PortAudio's thread. Must be short and must never block."""
        frame = AudioFrame(
            pcm=pcm,
            sample_rate=self._settings.audio.sample_rate,
            sequence=self._sequence,
            timestamp=timestamp,
        )
        self._sequence += 1
        if not self._queue.push(frame):
            # The consumer is behind. We dropped the oldest frame rather than
            # stalling the device; record it so the utterance can admit the gap.
            self._segmenter.note_dropped()

    # -- the audio worker thread -----------------------------------------

    def _run_worker(self) -> None:
        """VAD, segmentation and metering. Never touches the GUI or the loop."""
        _log.debug("audio worker started")
        while not self._stop.is_set():
            frame = self._queue.pop(timeout=_POLL_TIMEOUT_S)
            if frame is None:
                continue
            try:
                self._process_frame(frame)
            except Exception:
                _log.exception("audio worker failed on a frame")
        _log.debug("audio worker stopped")

    def _process_frame(self, frame: AudioFrame) -> None:
        self._frames_processed += 1
        chunk = AudioChunk(pcm=frame.pcm, sample_rate=frame.sample_rate)

        decision = self._vad.process(chunk)
        signal = self._segmenter.push(frame, decision)

        level = self._meter.push(frame.pcm, now=frame.timestamp, duration_s=frame.duration_s)
        if level is not None:
            self._publish(AudioLevel(source="audio", rms=level, direction="input"))

        if self._meter.check_dead_microphone():
            self._publish(
                AudioDeviceErrorEvent(
                    source="audio",
                    message=(
                        "The microphone is open but delivering silence. On Windows "
                        "check Settings > Privacy & security > Microphone."
                    ),
                )
            )

        match signal:
            case SpeechBegan():
                self._publish(SpeechStarted(source="audio"))
            case SpeechEnded(utterance=utterance):
                self._utterances += 1
                self._publish(SpeechEndedEvent(source="audio", duration_s=utterance.duration_s))
                self._submit_utterance(utterance)
            case SpeechDiscarded(reason=reason):
                self._discarded += 1
                _log.debug("discarded audio: %s", reason)
            case None:
                pass

    # -- crossing back to the kernel loop --------------------------------

    def _publish(self, event: object) -> None:
        """Hand an event to the kernel loop from the worker thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._bus.publish_soon, event)  # type: ignore[arg-type]

    def _submit_utterance(self, utterance: Utterance) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._transcribe(utterance), loop)

    # -- transcription (kernel loop + executor) --------------------------

    async def _transcribe(self, utterance: Utterance) -> None:
        """Transcribe an utterance, then return B.O.B. to IDLE.

        Runs on the kernel loop; the actual inference goes to an executor so the
        loop stays responsive.
        """
        if utterance.is_empty:
            await self._return_to_idle("empty utterance")
            return

        # Capture stops while we transcribe: Phase 2 handles one utterance at a
        # time, and leaving the microphone open would queue audio nobody reads.
        self._close_stream()

        try:
            await self._state.transition(BobState.TRANSCRIBING, reason="utterance captured")
        except Exception:
            _log.exception("could not enter TRANSCRIBING")
            return

        await self._bus.publish(
            TranscriptionStarted(
                source="stt",
                duration_s=utterance.duration_s,
                model=getattr(self._stt, "name", "stt"),
            )
        )
        if utterance.truncated:
            _log.warning(
                "utterance hit the %.0fs limit and was cut",
                self._settings.vad.max_utterance_s,
            )
        if utterance.dropped_frames:
            _log.warning("utterance is missing %d dropped frames", utterance.dropped_frames)

        chunk = AudioChunk(pcm=utterance.pcm, sample_rate=utterance.sample_rate)
        started = time.perf_counter()
        try:
            transcript = await asyncio.get_running_loop().run_in_executor(
                None, self._blocking_transcribe, chunk
            )
        except Exception as exc:
            self._failures += 1
            _log.exception("transcription failed")
            await self._bus.publish(TranscriptionFailed(source="stt", message=str(exc)))
            await self._recover_from_error(str(exc))
            return

        elapsed = time.perf_counter() - started
        rtf = elapsed / utterance.duration_s if utterance.duration_s else 0.0
        _log.info(
            "transcribed %.1fs in %.2fs (RTF %.2f): %r",
            utterance.duration_s,
            elapsed,
            rtf,
            transcript.text,
        )

        if transcript.is_empty:
            await self._return_to_idle("no speech recognised")
            return

        await self._bus.publish(
            TranscriptReady(
                source="stt",
                text=transcript.text,
                language=transcript.language,
                confidence=transcript.confidence,
            )
        )
        await self._return_to_idle("transcript delivered")

    def _blocking_transcribe(self, chunk: AudioChunk):  # type: ignore[no-untyped-def]
        """Runs in the executor. Emits partials when the provider offers them."""
        emit_partials = self._settings.stt.emit_partials and hasattr(
            self._stt, "transcribe_segments"
        )
        if emit_partials:
            latest = ""
            for text, is_final in self._stt.transcribe_segments(chunk):  # type: ignore[attr-defined]
                latest = text
                if not is_final and text:
                    self._publish(
                        TranscriptPartial(
                            source="stt", text=text, language=self._settings.stt.language or "el"
                        )
                    )
            from bob.providers.base import Transcript

            return Transcript(
                text=latest,
                language=self._settings.stt.language or "el",
                duration_s=chunk.duration_s,
            )

        return asyncio.run(self._stt.transcribe(chunk))

    # -- recovery --------------------------------------------------------

    async def _return_to_idle(self, reason: str) -> None:
        if self._state.state is not BobState.IDLE:
            with contextlib.suppress(Exception):
                await self._state.transition(BobState.IDLE, reason=reason)

    async def _fail_device(self, message: str) -> None:
        _log.error("microphone unavailable: %s", message)
        await self._bus.publish(AudioDeviceErrorEvent(source="audio", message=message))
        await self._recover_from_error(message)

    async def _recover_from_error(self, reason: str) -> None:
        """Show the fault, then return to IDLE so B.O.B. stays usable.

        A failed microphone or a failed transcription is not a reason to require
        an application restart.
        """
        with contextlib.suppress(Exception):
            await self._state.to_error(reason=reason)
        await asyncio.sleep(self._settings.audio.error_recovery_s)
        await self._return_to_idle("recovered")

    def _reset_for_utterance(self) -> None:
        self._segmenter.reset()
        self._vad.reset()
        self._meter.reset()
