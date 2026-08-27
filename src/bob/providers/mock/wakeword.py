"""Mock wake-word detector."""

from __future__ import annotations

from typing import Any

from bob.providers.base import AudioChunk, WakeDetection
from bob.providers.registry import registry


class MockWakeWord:
    """Never fires on audio; fires when :meth:`trigger` is called.

    This keeps Phase 0 tests free of audio fixtures while exercising the same
    code path the real detector will use.
    """

    def __init__(self, *, keyword: str = "bob") -> None:
        self.keyword = keyword
        self._armed = False

    @property
    def name(self) -> str:
        return "mock-wakeword"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def reset(self) -> None:
        self._armed = False

    def trigger(self) -> None:
        """Arm a detection to be returned by the next :meth:`process` call."""
        self._armed = True

    def process(self, frame: AudioChunk) -> WakeDetection | None:
        if self._armed:
            self._armed = False
            return WakeDetection(keyword=self.keyword, confidence=1.0)
        return None


@registry.register("wakeword", "mock")
def _factory(**kwargs: Any) -> MockWakeWord:
    return MockWakeWord(keyword=str(kwargs.get("keyword", "bob")))
