"""Mock speech-to-text."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Any

from bob.providers.base import AudioChunk, Transcript
from bob.providers.registry import registry


class MockSTT:
    """Returns queued transcripts; useful for driving the pipeline in tests."""

    def __init__(self, *, scripted: Sequence[str] | None = None) -> None:
        self._queue: deque[str] = deque(scripted or [])
        self.default = "δοκιμή"

    @property
    def name(self) -> str:
        return "mock-stt"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def push(self, text: str) -> None:
        self._queue.append(text)

    async def transcribe(self, audio: AudioChunk, *, language: str | None = None) -> Transcript:
        text = self._queue.popleft() if self._queue else self.default
        return Transcript(
            text=text,
            language=language or "el",
            confidence=1.0,
            duration_s=audio.duration_s,
        )


@registry.register("stt", "mock")
def _factory(**kwargs: Any) -> MockSTT:
    return MockSTT(scripted=kwargs.get("scripted"))
