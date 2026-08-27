"""Deterministic mock LLM."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

from bob.providers.base import LLMChunk, Message
from bob.providers.registry import registry

#: Canned Greek replies, so the mock sounds like B.O.B. rather than like a stub.
_REPLIES: dict[str, str] = {
    "hello": "Γεια σου. Είμαι εδώ.",
    "status": "Όλα καλά, τρέχω κανονικά.",
}
_DEFAULT = "Σε ακούω. Πες μου τι θέλεις."


class MockLLM:
    """Echoes a canned Greek reply, streamed word by word."""

    def __init__(self, *, delay_s: float = 0.0, scripted: Sequence[str] | None = None) -> None:
        self._delay = delay_s
        self._scripted = list(scripted or [])
        self.calls: list[list[Message]] = []

    @property
    def name(self) -> str:
        return "mock-llm"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def generate(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMChunk]:
        self.calls.append(list(messages))
        if self._scripted:
            reply = self._scripted.pop(0)
        else:
            last = next((m.content for m in reversed(messages) if m.role == "user"), "")
            reply = _REPLIES.get(last.strip().lower(), _DEFAULT)

        for word in reply.split():
            if self._delay:
                await asyncio.sleep(self._delay)
            yield LLMChunk(text=word + " ")
        yield LLMChunk(done=True, usage={"prompt_tokens": 0, "completion_tokens": 0})


@registry.register("llm", "mock")
def _factory(**kwargs: Any) -> MockLLM:
    return MockLLM(delay_s=float(kwargs.get("delay_s", 0.0)))
