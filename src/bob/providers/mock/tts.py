"""Mock text-to-speech."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from bob.providers.base import AudioChunk
from bob.providers.registry import registry

_SAMPLE_RATE = 22_050


class MockTTS:
    """Emits silent PCM chunks at roughly speech pace.

    Chunked output is the point: it is what lets playback be cancelled halfway
    through when the user interrupts.
    """

    def __init__(self, *, delay_s: float = 0.0, chars_per_chunk: int = 24) -> None:
        self._delay = delay_s
        self._chars = chars_per_chunk
        self.spoken: list[str] = []

    @property
    def name(self) -> str:
        return "mock-tts"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def synthesize(
        self, text: str, *, voice: str | None = None, speed: float | None = None
    ) -> AsyncIterator[AudioChunk]:
        self.spoken.append(text)
        pieces = [text[i : i + self._chars] for i in range(0, max(len(text), 1), self._chars)]
        for piece in pieces:
            if self._delay:
                await asyncio.sleep(self._delay)
            # ~60 ms of silence per character, 16-bit mono.
            frames = int(_SAMPLE_RATE * 0.06 * len(piece))
            yield AudioChunk(pcm=b"\x00\x00" * frames, sample_rate=_SAMPLE_RATE)


@registry.register("tts", "mock")
def _factory(**kwargs: Any) -> MockTTS:
    return MockTTS(delay_s=float(kwargs.get("delay_s", 0.0)))
