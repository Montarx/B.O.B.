"""Amplitude metering for the UI, and a dead-microphone detector.

Two jobs, both pure:

1. Turn raw amplitude into a value the core animation can use. Raw RMS looks
   wrong on screen — speech sits around 0.02-0.15 of full scale, so a linear
   meter barely moves. This applies a perceptual curve and a fast-attack,
   slow-release envelope so the orb responds like an ear rather than like a
   voltmeter.

2. Notice when the microphone is delivering digital silence. On Windows 11 a
   revoked microphone permission does not raise an error — the stream opens
   happily and delivers zeros forever. Without this check that failure is
   invisible and looks like "B.O.B. is ignoring me".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bob.audio.frames import peak_level, rms_level

#: Below this peak, a frame is indistinguishable from digital silence.
SILENCE_FLOOR = 1e-4


@dataclass(frozen=True, slots=True)
class LevelConfig:
    #: How often levels are published to the UI. 20 Hz is smooth at 60 fps
    #: without pushing an event per audio frame.
    update_hz: float = 20.0
    #: RMS mapped to a full meter. Normal speech peaks well below full scale.
    reference_rms: float = 0.18
    #: Envelope constants, in seconds.
    attack_s: float = 0.02
    release_s: float = 0.18
    #: Seconds of pure digital silence before the microphone is called dead.
    silence_alarm_s: float = 4.0


class LevelMeter:
    """Converts frames into a smoothed 0..1 level, rate-limited for the UI."""

    def __init__(self, config: LevelConfig | None = None) -> None:
        self._config = config or LevelConfig()
        self._envelope = 0.0
        self._last_emit = float("-inf")
        self._silent_for = 0.0
        self._alarm_raised = False

    @property
    def level(self) -> float:
        return self._envelope

    @property
    def silent_seconds(self) -> float:
        return self._silent_for

    def reset(self) -> None:
        self._envelope = 0.0
        self._last_emit = float("-inf")
        self._silent_for = 0.0
        self._alarm_raised = False

    def push(self, pcm: bytes, *, now: float, duration_s: float) -> float | None:
        """Feed a frame. Returns a level to publish, or ``None`` if rate-limited."""
        target = self._shape(rms_level(pcm))

        # Fast attack, slow release: rises with the voice, falls gently.
        tau = self._config.attack_s if target > self._envelope else self._config.release_s
        alpha = 1.0 - math.exp(-duration_s / tau) if tau > 0 else 1.0
        self._envelope += (target - self._envelope) * alpha

        if peak_level(pcm) < SILENCE_FLOOR:
            self._silent_for += duration_s
        else:
            self._silent_for = 0.0
            self._alarm_raised = False

        interval = 1.0 / self._config.update_hz if self._config.update_hz > 0 else 0.0
        if now - self._last_emit < interval:
            return None
        self._last_emit = now
        return self._envelope

    def _shape(self, rms: float) -> float:
        """Perceptual curve: compress the top, expand the quiet part."""
        if rms <= 0.0:
            return 0.0
        normalised = min(1.0, rms / self._config.reference_rms)
        return float(normalised**0.6)

    def check_dead_microphone(self) -> bool:
        """True exactly once when sustained digital silence is first detected."""
        if self._silent_for < self._config.silence_alarm_s or self._alarm_raised:
            return False
        self._alarm_raised = True
        return True
