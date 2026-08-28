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


def load_all() -> list[str]:
    """Import every provider module so it registers itself.

    Import failures are tolerated and reported rather than fatal: a machine
    without the ``voice`` extra should still start B.O.B. with mock providers
    and tell the user what is missing, not refuse to launch.

    Returns the names of the provider groups that could not be loaded.
    """
    import importlib
    import logging

    log = logging.getLogger("bob.app.providers")
    missing: list[str] = []
    for module in (
        "bob.providers.mock",
        "bob.providers.vad.energy",
        "bob.providers.vad.silero",
        "bob.providers.stt.faster_whisper",
    ):
        try:
            importlib.import_module(module)
        except Exception as exc:
            missing.append(module)
            log.warning("provider module %s unavailable: %s", module, exc)
    return missing


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
    "load_all",
    "registry",
]
