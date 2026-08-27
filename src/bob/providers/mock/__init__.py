"""Mock providers.

These exist so the whole pipeline can be wired, run and tested in Phase 0 without
Ollama, Whisper, Piper, a microphone or a GPU. Every real provider added in later
phases must satisfy the same Protocol, and the same tests should pass against it.
"""

from bob.providers.mock import llm, memory, stt, tts, vad, vision, wakeword

__all__ = ["llm", "memory", "stt", "tts", "vad", "vision", "wakeword"]
