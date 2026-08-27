"""Swappable capability providers (LLM, STT, TTS, wake word, VAD, memory, vision)."""

from bob.providers.base import (
    AudioChunk,
    LLMChunk,
    LLMProvider,
    MemoryProvider,
    MemoryRecord,
    Message,
    STTProvider,
    Transcript,
    TTSProvider,
    VADDecision,
    VADProvider,
    VisionProvider,
    WakeWordProvider,
)
from bob.providers.registry import ProviderRegistry, registry

__all__ = [
    "AudioChunk",
    "LLMChunk",
    "LLMProvider",
    "MemoryProvider",
    "MemoryRecord",
    "Message",
    "ProviderRegistry",
    "STTProvider",
    "TTSProvider",
    "Transcript",
    "VADDecision",
    "VADProvider",
    "VisionProvider",
    "WakeWordProvider",
    "registry",
]
