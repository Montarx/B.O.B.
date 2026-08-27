"""Mock voice-activity detection."""

from __future__ import annotations

import array
import math
from typing import Any

from bob.providers.base import AudioChunk, VADDecision
from bob.providers.registry import registry


def _rms16(pcm: bytes) -> float:
    """RMS of signed 16-bit little-endian PCM.

    Implemented with :mod:`array` rather than ``audioop``, which was removed in
    Python 3.13.
    """
    if len(pcm) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    return math.sqrt(sum(float(s) * s for s in samples) / len(samples))


class MockVAD:
    """Plain RMS threshold. Good enough to exercise the plumbing, not for production."""

    def __init__(self, *, threshold: float = 500.0) -> None:
        self.threshold = threshold
        self.forced: bool | None = None

    @property
    def name(self) -> str:
        return "mock-vad"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def reset(self) -> None:
        self.forced = None

    def process(self, frame: AudioChunk) -> VADDecision:
        if self.forced is not None:
            return VADDecision(is_speech=self.forced, rms=self.threshold + 1)
        return VADDecision(is_speech=(rms := _rms16(frame.pcm)) >= self.threshold, rms=rms)


@registry.register("vad", "mock")
def _factory(**kwargs: Any) -> MockVAD:
    return MockVAD(threshold=float(kwargs.get("threshold", 500.0)))
