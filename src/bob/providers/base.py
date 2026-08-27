"""Provider interfaces.

These are :class:`typing.Protocol` definitions rather than abstract base classes.
Structural typing means an implementation does not have to import or inherit from
B.O.B. to satisfy an interface — which keeps third-party adapters and test doubles
trivial, and keeps the plugin surface loose.

**Streaming is part of the contract, not an optimisation.**
``LLMProvider.generate`` and ``TTSProvider.synthesize`` are async iterators because:

* streaming tokens lets us start speaking the first sentence while the rest is still
  being generated, which is the single biggest win in perceived latency;
* streaming audio in chunks is what makes barge-in (interrupting B.O.B. mid-sentence)
  possible at all.

Retro-fitting either of these later would mean rewriting every caller, so they are
baked in from day one even though Phase 0 only ships mocks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]


# --------------------------------------------------------------------------
# Shared data types
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of conversation handed to the LLM."""

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A structured tool invocation requested by the model.

    Note that ``arguments`` is a plain dict here — it has *not* been validated yet.
    Validation happens in the tool layer against the tool's Pydantic schema. The
    model never produces an executable string.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMChunk:
    """One fragment of a streamed model response."""

    text: str = ""
    tool_call: ToolCall | None = None
    done: bool = False
    #: Populated on the final chunk when the provider reports usage.
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """A block of PCM audio."""

    pcm: bytes
    sample_rate: int
    channels: int = 1
    #: Sample width in bytes; 2 == 16-bit signed, which is what B.O.B. uses throughout.
    sample_width: int = 2

    @property
    def duration_s(self) -> float:
        frames = len(self.pcm) / (self.sample_width * self.channels)
        return frames / self.sample_rate if self.sample_rate else 0.0


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str = "el"
    confidence: float = 1.0
    duration_s: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class VADDecision:
    """Voice-activity verdict for a single audio frame."""

    is_speech: bool
    rms: float = 0.0


@dataclass(frozen=True, slots=True)
class WakeDetection:
    keyword: str
    confidence: float


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One deliberate, inspectable, deletable memory.

    Long-term memory is never an automatic transcript dump: every record has an id
    the user can ask about and remove.
    """

    id: str
    text: str
    kind: Literal["fact", "preference", "task"] = "fact"
    tags: tuple[str, ...] = ()
    created_at: float = 0.0
    source: str = "user"
    score: float = 0.0


# --------------------------------------------------------------------------
# Lifecycle mixin shared by every provider
# --------------------------------------------------------------------------


@runtime_checkable
class Provider(Protocol):
    """Common lifecycle every provider implements."""

    @property
    def name(self) -> str:
        """Short identifier, e.g. ``"faster-whisper"``. Shown in the UI."""
        ...

    async def start(self) -> None:
        """Load models / open devices. May be slow; never called on the GUI thread."""
        ...

    async def aclose(self) -> None:
        """Release resources. Must be safe to call twice."""
        ...


# --------------------------------------------------------------------------
# Capability interfaces
# --------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Provider, Protocol):
    """Reasoning engine. Ollama in Phase 3; cloud adapters possible later."""

    def generate(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Stream a response. ``tools`` are JSON schemas the model may call."""
        ...


@runtime_checkable
class STTProvider(Provider, Protocol):
    """Speech to text."""

    async def transcribe(self, audio: AudioChunk, *, language: str | None = None) -> Transcript: ...


@runtime_checkable
class TTSProvider(Provider, Protocol):
    """Text to speech."""

    def synthesize(
        self, text: str, *, voice: str | None = None, speed: float | None = None
    ) -> AsyncIterator[AudioChunk]:
        """Stream synthesised audio so playback can start early and be cancelled."""
        ...


@runtime_checkable
class VADProvider(Provider, Protocol):
    """Voice activity detection over a stream of fixed-size frames."""

    def process(self, frame: AudioChunk) -> VADDecision:
        """Synchronous and cheap by contract — this runs per audio frame."""
        ...

    def reset(self) -> None: ...


@runtime_checkable
class WakeWordProvider(Provider, Protocol):
    """Always-on keyword spotting."""

    def process(self, frame: AudioChunk) -> WakeDetection | None:
        """Synchronous and cheap by contract — this runs per audio frame."""
        ...

    def reset(self) -> None: ...


@runtime_checkable
class MemoryProvider(Provider, Protocol):
    """Long-term, deliberate memory."""

    async def remember(
        self,
        text: str,
        *,
        kind: str = "fact",
        tags: Sequence[str] = (),
        source: str = "user",
    ) -> MemoryRecord: ...

    async def recall(self, query: str, *, limit: int = 8) -> list[MemoryRecord]: ...

    async def forget(self, record_id: str) -> bool:
        """Return ``True`` if a record was actually removed."""
        ...

    async def list_all(self, *, kind: str | None = None) -> list[MemoryRecord]:
        """Full inspection — the user must always be able to see what B.O.B. knows."""
        ...


@runtime_checkable
class VisionProvider(Provider, Protocol):
    """Screen understanding. Only ever invoked on an explicit request."""

    async def describe(
        self, image_png: bytes, *, prompt: str = "", max_tokens: int = 512
    ) -> str: ...
