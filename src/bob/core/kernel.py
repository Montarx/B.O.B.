"""The kernel: B.O.B.'s headless core.

The kernel owns the event bus, the state machine, the providers and the tool
registry, and knows nothing about Qt. That is the point — everything below can be
started, driven and tested with no GUI, no audio device and no models:

    settings = load_settings()
    kernel = Kernel(settings)
    await kernel.start()

Phase 1 adds a UI process that *observes* the kernel through the bus and *commands*
it through method calls. The kernel never reaches into the UI.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any

from bob.config.loader import load_persona
from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.errors import BobError
from bob.core.events import ErrorOccurred, Event, EventType
from bob.core.state_machine import StateMachine
from bob.core.states import BobState
from bob.providers import registry as provider_registry
from bob.providers.base import (
    LLMProvider,
    MemoryProvider,
    STTProvider,
    TTSProvider,
    VADProvider,
    VisionProvider,
    WakeWordProvider,
)
from bob.tools.audit import AuditLog
from bob.tools.builtin import default_tools
from bob.tools.permissions import PermissionBroker
from bob.tools.registry import ToolRegistry
from bob.utils import paths

_log = logging.getLogger("bob.app.kernel")


class Kernel:
    """Composition root. Builds every subsystem from configuration and wires them."""

    def __init__(self, settings: Settings, *, bus: EventBus | None = None) -> None:
        self.settings = settings
        self.bus = bus or EventBus(name="bob")
        self.state = StateMachine(self.bus)

        self.audit = AuditLog(
            paths.audit_path(),
            enabled=settings.security.audit_enabled,
            redact_keys=settings.security.redact_keys,
        )
        self.permissions = PermissionBroker(settings.security, self.bus)
        self.tools = ToolRegistry(
            self.bus,
            self.permissions,
            self.audit,
            default_timeout_s=settings.security.tool_timeout_s,
        )

        # Providers are created lazily in start(), so construction never blocks.
        self.llm: LLMProvider | None = None
        self.stt: STTProvider | None = None
        self.tts: TTSProvider | None = None
        self.vad: VADProvider | None = None
        self.wakeword: WakeWordProvider | None = None
        self.memory: MemoryProvider | None = None
        self.vision: VisionProvider | None = None

        self.persona: str = ""
        self._started = False

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        """Bring B.O.B. online: load persona, build providers, register tools."""
        if self._started:
            return
        await self.state.transition(BobState.STARTING, reason="kernel.start")
        await self.bus.publish(Event(type=EventType.KERNEL_STARTING, source="kernel"))

        try:
            self.persona = load_persona(self.settings.personality.persona)
            self._build_providers()
            await self._start_providers()
            self.tools.add_all(default_tools())
        except BobError as exc:
            _log.exception("startup failed")
            await self.bus.publish(
                ErrorOccurred(
                    source="kernel",
                    component="kernel.start",
                    message=str(exc),
                    fatal=True,
                )
            )
            await self.state.to_error(reason=str(exc))
            raise

        self._started = True
        await self.state.transition(BobState.IDLE, reason="ready")
        await self.bus.publish(Event(type=EventType.KERNEL_READY, source="kernel"))
        _log.info(
            "B.O.B. online — llm=%s stt=%s tts=%s tools=%d",
            self.settings.llm.provider,
            self.settings.stt.provider,
            self.settings.tts.provider,
            len(self.tools),
        )

    async def aclose(self) -> None:
        """Shut down cleanly. Safe to call more than once."""
        if not self._started:
            await self.bus.aclose()
            return
        await self.bus.publish(Event(type=EventType.KERNEL_STOPPING, source="kernel"))
        for provider in self._providers():
            try:
                await provider.aclose()
            except Exception:  # one bad provider must not block shutdown
                _log.exception("error closing provider %r", provider)
        await self.state.transition(BobState.OFFLINE, reason="shutdown")
        await self.bus.aclose()
        self._started = False

    async def __aenter__(self) -> Kernel:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- provider wiring -------------------------------------------------

    def _build_providers(self) -> None:
        """Instantiate providers named in configuration. No concrete imports here."""
        create = provider_registry.create
        s = self.settings
        self.llm = create("llm", s.llm.provider)
        self.stt = create("stt", s.stt.provider)
        self.tts = create("tts", s.tts.provider)
        self.vad = create("vad", s.vad.provider)
        self.wakeword = create("wakeword", s.wakeword.provider)
        self.memory = create("memory", s.memory.provider)
        self.vision = create("vision", s.vision.provider)

    def _providers(self) -> list[Any]:
        return [
            p
            for p in (
                self.llm,
                self.stt,
                self.tts,
                self.vad,
                self.wakeword,
                self.memory,
                self.vision,
            )
            if p is not None
        ]

    async def _start_providers(self) -> None:
        for provider in self._providers():
            await provider.start()

    # -- introspection ---------------------------------------------------

    @property
    def started(self) -> bool:
        return self._started

    def describe(self) -> dict[str, Any]:
        """Snapshot for the UI's status panel and for debugging."""
        return {
            "state": self.state.state.value,
            "persona": self.settings.personality.persona,
            "providers": {
                "llm": getattr(self.llm, "name", None),
                "stt": getattr(self.stt, "name", None),
                "tts": getattr(self.tts, "name", None),
                "vad": getattr(self.vad, "name", None),
                "wakeword": getattr(self.wakeword, "name", None),
                "memory": getattr(self.memory, "name", None),
                "vision": getattr(self.vision, "name", None),
            },
            "tools": self.tools.names(),
        }
