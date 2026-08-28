"""Energy-threshold VAD.

A dependency-free fallback for when the Silero model is unavailable. It is
honestly not good enough for a noisy desktop — a fan or a keyboard will trigger
it — but it keeps B.O.B. usable rather than dead, and it makes the pipeline
runnable in CI with no model download.

It adapts to the room: the threshold floats above a rolling estimate of the noise
floor, which is the minimum needed to avoid being useless in a quiet room *and*
in a loud one.
"""

from __future__ import annotations

import logging
from typing import Any

from bob.audio.frames import rms_level
from bob.providers.base import AudioChunk, VADDecision
from bob.providers.registry import registry

_log = logging.getLogger("bob.app.audio.vad")


class EnergyVAD:
    """Adaptive RMS gate."""

    def __init__(
        self,
        *,
        threshold: float = 0.02,
        noise_adapt: float = 0.02,
        margin: float = 3.0,
    ) -> None:
        self._base_threshold = threshold
        self._noise_adapt = noise_adapt
        self._margin = margin
        self._noise_floor = threshold / margin

    @property
    def name(self) -> str:
        return "energy-vad"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def reset(self) -> None:
        self._noise_floor = self._base_threshold / self._margin

    def process(self, frame: AudioChunk) -> VADDecision:
        level = rms_level(frame.pcm)
        threshold = max(self._base_threshold, self._noise_floor * self._margin)
        is_speech = level >= threshold

        # Asymmetric noise tracking. Falling fast and rising slowly means:
        #  * a burst of speech barely moves the floor, so it stays sensitive;
        #  * but *sustained* loud input does eventually raise it, so a noisy room
        #    settles instead of being classified as one endless utterance.
        # Tracking only while "not speech" would deadlock: if room tone starts
        # above the threshold it would read as speech forever and never adapt.
        rate = self._noise_adapt if level < self._noise_floor else self._noise_adapt * 0.25
        self._noise_floor += (level - self._noise_floor) * rate
        return VADDecision(is_speech=is_speech, rms=level)


@registry.register("vad", "energy")
def _factory(**kwargs: Any) -> EnergyVAD:
    return EnergyVAD(threshold=float(kwargs.get("threshold", 0.02)))
