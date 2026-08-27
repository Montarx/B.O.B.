"""Mock vision provider."""

from __future__ import annotations

from typing import Any

from bob.providers.registry import registry


class MockVision:
    """Returns a fixed Greek description and records what it was asked."""

    def __init__(self, *, reply: str = "Βλέπω μια οθόνη με ένα παράθυρο ανοιχτό.") -> None:
        self.reply = reply
        self.calls: list[tuple[int, str]] = []

    @property
    def name(self) -> str:
        return "mock-vision"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def describe(self, image_png: bytes, *, prompt: str = "", max_tokens: int = 512) -> str:
        self.calls.append((len(image_png), prompt))
        return self.reply


@registry.register("vision", "mock")
def _factory(**kwargs: Any) -> MockVision:
    return MockVision()
