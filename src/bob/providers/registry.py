"""Provider registry: maps ``(kind, name)`` from config to a concrete factory.

This is the seam that makes the whole "swap any component" requirement real. The
kernel never imports ``FasterWhisperSTT``; it asks the registry for whatever
``stt.provider`` says. Adding a provider is a decorator, not a core edit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from bob.core.errors import ProviderNotFoundError

_log = logging.getLogger("bob.app.providers")

ProviderKind = Literal["llm", "stt", "tts", "vad", "wakeword", "memory", "vision"]

KINDS: tuple[ProviderKind, ...] = (
    "llm",
    "stt",
    "tts",
    "vad",
    "wakeword",
    "memory",
    "vision",
)

T = TypeVar("T")
Factory = Callable[..., Any]


class ProviderRegistry:
    """Name-to-factory table, one namespace per capability kind."""

    def __init__(self) -> None:
        self._factories: dict[ProviderKind, dict[str, Factory]] = {kind: {} for kind in KINDS}

    def register(
        self, kind: ProviderKind, name: str, *, replace: bool = False
    ) -> Callable[[Factory], Factory]:
        """Decorator registering a provider factory under ``kind``/``name``."""

        def decorator(factory: Factory) -> Factory:
            bucket = self._factories[kind]
            if name in bucket and not replace:
                raise ValueError(f"provider {kind}/{name} already registered")
            bucket[name] = factory
            _log.debug("registered provider %s/%s", kind, name)
            return factory

        return decorator

    def create(self, kind: ProviderKind, name: str, /, **kwargs: Any) -> Any:
        """Instantiate a provider, raising a helpful error when it is unknown."""
        bucket = self._factories[kind]
        factory = bucket.get(name)
        if factory is None:
            available = ", ".join(sorted(bucket)) or "none"
            raise ProviderNotFoundError(f"unknown {kind} provider {name!r}; available: {available}")
        return factory(**kwargs)

    def available(self, kind: ProviderKind) -> list[str]:
        return sorted(self._factories[kind])

    def clear(self) -> None:
        for bucket in self._factories.values():
            bucket.clear()


#: Process-wide registry. Providers register themselves on import.
registry = ProviderRegistry()
