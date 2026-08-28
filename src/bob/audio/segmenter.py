"""Speech segmentation: turning a stream of VAD verdicts into utterances.

This is a **pure state machine**. It takes frames and per-frame VAD decisions and
returns signals; it does no I/O, owns no threads, and never touches hardware.
That is deliberate — segmentation is where the subtle bugs live (clipped first
syllables, utterances that never end, spurious triggers on a cough), and keeping
it pure means all of that is testable with synthetic input.

The state machine::

      ┌──────────────────────── silence ◀───────────────────┐
      ▼                                                     │
    ARMED ──speech──▶ CANDIDATE ──sustained──▶ SPEECH ──silence──▶ TRAILING
      ▲                    │                      ▲                    │
      └──── too short ─────┘                      └──── speech ────────┘
                                                                       │
                                                        end silence ───┴──▶ utterance

* **ARMED** — listening, filling the pre-roll ring.
* **CANDIDATE** — VAD says speech, but not yet for ``min_speech_ms``. A cough or
  a door closing dies here and never reaches the STT model.
* **SPEECH** — confirmed. Frames accumulate.
* **TRAILING** — VAD says silence, but we wait ``end_silence_ms`` before deciding
  the user has finished, so a natural pause mid-sentence does not cut them off.

Pre-roll matters: VAD is always slightly late, so by the time speech is confirmed
the first syllable has already passed. The emitted utterance is
``pre-roll + candidate frames + speech frames``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from bob.audio.frames import (
    SAMPLE_RATE,
    AudioFrame,
    PreRollBuffer,
    Utterance,
    join_frames,
)
from bob.providers.base import VADDecision

_log = logging.getLogger("bob.app.audio.segmenter")


class SegmentState(StrEnum):
    ARMED = "armed"
    CANDIDATE = "candidate"
    SPEECH = "speech"
    TRAILING = "trailing"


class DiscardReason(StrEnum):
    TOO_SHORT = "too_short"
    NO_SPEECH = "no_speech"


@dataclass(frozen=True, slots=True)
class SegmentationConfig:
    """Tunables, all in milliseconds so they read the way people think."""

    #: Sustained speech required before an utterance is considered real.
    min_speech_ms: int = 250
    #: Silence that ends an utterance. Long enough to survive a mid-sentence pause.
    end_silence_ms: int = 700
    #: Audio kept before speech was detected, so the first syllable survives.
    pre_roll_ms: int = 320
    #: Hard ceiling; the utterance is cut and flagged ``truncated``.
    max_utterance_s: float = 20.0
    #: Silence kept on the end. A little helps Whisper decide the audio finished.
    tail_silence_ms: int = 200
    #: Below this, an utterance is dropped as too short to be real speech.
    min_utterance_ms: int = 300

    def frames_for_ms(self, milliseconds: int, frame_ms: float) -> int:
        if frame_ms <= 0:
            return 0
        return max(0, round(milliseconds / frame_ms))


@dataclass(frozen=True, slots=True)
class SpeechBegan:
    """Speech has been confirmed. The UI can show that B.O.B. is hearing."""

    timestamp: float = 0.0


@dataclass(frozen=True, slots=True)
class SpeechEnded:
    """A complete utterance is ready for transcription."""

    utterance: Utterance
    timestamp: float = 0.0


@dataclass(frozen=True, slots=True)
class SpeechDiscarded:
    """Something triggered the VAD but was not speech worth transcribing."""

    reason: DiscardReason
    timestamp: float = 0.0


SegmentSignal = SpeechBegan | SpeechEnded | SpeechDiscarded


class Segmenter:
    """Accumulates frames into utterances according to VAD verdicts."""

    def __init__(
        self,
        config: SegmentationConfig | None = None,
        *,
        frame_ms: float = 32.0,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._config = config or SegmentationConfig()
        self._frame_ms = frame_ms
        self._sample_rate = sample_rate

        self._pre_roll = PreRollBuffer(
            self._config.frames_for_ms(self._config.pre_roll_ms, frame_ms)
        )
        self._state = SegmentState.ARMED
        self._candidate: list[AudioFrame] = []
        self._speech: list[AudioFrame] = []
        self._trailing: list[AudioFrame] = []
        self._dropped_frames = 0

        self._min_speech_frames = max(
            1, self._config.frames_for_ms(self._config.min_speech_ms, frame_ms)
        )
        self._end_silence_frames = max(
            1, self._config.frames_for_ms(self._config.end_silence_ms, frame_ms)
        )
        self._tail_frames = self._config.frames_for_ms(self._config.tail_silence_ms, frame_ms)
        self._max_frames = max(1, int(self._config.max_utterance_s * 1000 / frame_ms))
        self._min_utterance_frames = max(
            1, self._config.frames_for_ms(self._config.min_utterance_ms, frame_ms)
        )

    # -- introspection ---------------------------------------------------

    @property
    def state(self) -> SegmentState:
        return self._state

    @property
    def config(self) -> SegmentationConfig:
        return self._config

    @property
    def is_capturing(self) -> bool:
        """True once speech is confirmed and frames are being kept."""
        return self._state in {SegmentState.SPEECH, SegmentState.TRAILING}

    @property
    def captured_frames(self) -> int:
        return len(self._speech) + len(self._trailing)

    # -- the machine -----------------------------------------------------

    def push(self, frame: AudioFrame, decision: VADDecision) -> SegmentSignal | None:
        """Feed one frame and its VAD verdict. Returns a signal, or ``None``."""
        match self._state:
            case SegmentState.ARMED:
                return self._on_armed(frame, decision)
            case SegmentState.CANDIDATE:
                return self._on_candidate(frame, decision)
            case SegmentState.SPEECH:
                return self._on_speech(frame, decision)
            case SegmentState.TRAILING:
                return self._on_trailing(frame, decision)

    def _on_armed(self, frame: AudioFrame, decision: VADDecision) -> SegmentSignal | None:
        if decision.is_speech:
            self._candidate = [frame]
            self._state = SegmentState.CANDIDATE
            return None
        self._pre_roll.push(frame)
        return None

    def _on_candidate(self, frame: AudioFrame, decision: VADDecision) -> SegmentSignal | None:
        if not decision.is_speech:
            # A blip, not speech. Return the candidate frames to the pre-roll so
            # nothing is lost if real speech starts immediately afterwards.
            for candidate in self._candidate:
                self._pre_roll.push(candidate)
            self._pre_roll.push(frame)
            self._candidate.clear()
            self._state = SegmentState.ARMED
            return SpeechDiscarded(DiscardReason.TOO_SHORT, frame.timestamp)

        self._candidate.append(frame)
        if len(self._candidate) < self._min_speech_frames:
            return None

        # Confirmed: seed the utterance with pre-roll, then the candidate frames.
        self._speech = [*self._pre_roll.drain(), *self._candidate]
        self._candidate = []
        self._trailing = []
        self._state = SegmentState.SPEECH
        return SpeechBegan(frame.timestamp)

    def _on_speech(self, frame: AudioFrame, decision: VADDecision) -> SegmentSignal | None:
        if decision.is_speech:
            self._speech.append(frame)
            if self.captured_frames >= self._max_frames:
                return self._finish(frame, truncated=True)
            return None

        self._trailing = [frame]
        self._state = SegmentState.TRAILING
        return None

    def _on_trailing(self, frame: AudioFrame, decision: VADDecision) -> SegmentSignal | None:
        if decision.is_speech:
            # A pause, not the end. Fold the silence back in so the utterance
            # keeps its natural rhythm.
            self._speech.extend(self._trailing)
            self._speech.append(frame)
            self._trailing = []
            self._state = SegmentState.SPEECH
            if self.captured_frames >= self._max_frames:
                return self._finish(frame, truncated=True)
            return None

        self._trailing.append(frame)
        if len(self._trailing) >= self._end_silence_frames:
            return self._finish(frame, truncated=False)
        if self.captured_frames >= self._max_frames:
            return self._finish(frame, truncated=True)
        return None

    # -- completion ------------------------------------------------------

    def _finish(self, frame: AudioFrame, *, truncated: bool) -> SegmentSignal:
        speech_frames = list(self._speech)
        # Keep a little trailing silence; drop the rest so the model is not fed
        # most of a second of nothing.
        tail = self._trailing[: self._tail_frames] if self._tail_frames else []
        frames = [*speech_frames, *tail]
        dropped = self._dropped_frames
        self._reset_capture()

        if len(frames) < self._min_utterance_frames:
            return SpeechDiscarded(DiscardReason.TOO_SHORT, frame.timestamp)

        utterance = Utterance(
            pcm=join_frames(frames),
            sample_rate=self._sample_rate,
            pre_roll_s=self._pre_roll.duration_s,
            truncated=truncated,
            dropped_frames=dropped,
        )
        return SpeechEnded(utterance, frame.timestamp)

    def note_dropped(self, count: int = 1) -> None:
        """Record frames lost to backpressure, so the utterance can admit it."""
        self._dropped_frames += count

    def flush(self) -> SegmentSignal | None:
        """End the current utterance early, e.g. the user released the button."""
        if not self.is_capturing:
            self._reset_capture()
            return None
        frames = [*self._speech, *self._trailing]
        dropped = self._dropped_frames
        self._reset_capture()
        if len(frames) < self._min_utterance_frames:
            return SpeechDiscarded(DiscardReason.TOO_SHORT)
        return SpeechEnded(
            Utterance(
                pcm=join_frames(frames),
                sample_rate=self._sample_rate,
                pre_roll_s=self._pre_roll.duration_s,
                dropped_frames=dropped,
            )
        )

    def reset(self) -> None:
        """Return to ARMED and forget everything, including the pre-roll."""
        self._reset_capture()
        self._pre_roll.clear()

    def _reset_capture(self) -> None:
        self._state = SegmentState.ARMED
        self._candidate = []
        self._speech = []
        self._trailing = []
        self._dropped_frames = 0


def segment_all(
    segmenter: Segmenter,
    frames: Iterable[AudioFrame],
    decisions: Iterable[VADDecision],
) -> list[SegmentSignal]:
    """Run a whole recording through a segmenter. Used by tests and benchmarks."""
    signals: list[SegmentSignal] = []
    for frame, decision in zip(frames, decisions, strict=True):
        signal = segmenter.push(frame, decision)
        if signal is not None:
            signals.append(signal)
    return signals
