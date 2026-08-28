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

from bob.audio.pipeline import ListeningPipeline
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
        #: Owns the microphone. Built in start(), once providers exist.
        self.listening: ListeningPipeline | None = None
        #: Providers that failed to start, by kind. B.O.B. runs degraded rather
        #: than refusing to launch — a missing Whisper model should cost you the
        #: microphone, not the application.
        self.provider_errors: dict[str, str] = {}
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
            self._build_listening()
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
        if self.listening is not None:
            try:
                await self.listening.aclose()
            except Exception:
                _log.exception("error closing the listening pipeline")
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

    def _build_listening(self) -> None:
        """Assemble the microphone pipeline.

        Failure here is not fatal: B.O.B. is still useful without a microphone,
        so a missing PortAudio or an unavailable device leaves ``listening`` as
        ``None`` rather than preventing startup.
        """
        if self.vad is None or self.stt is None:
            return
        # No point opening a microphone we cannot transcribe from.
        blocked = {"stt", "vad"} & self.provider_errors.keys()
        if blocked:
            _log.warning(
                "microphone disabled: %s unavailable",
                ", ".join(sorted(blocked)),
            )
            return
        try:
            from bob.audio.capture import SoundDeviceBackend

            backend = SoundDeviceBackend()
        except Exception:
            _log.warning("audio capture unavailable; B.O.B. starts without a microphone")
            return
        self.listening = ListeningPipeline(
            self.settings, self.bus, self.state, self.vad, self.stt, backend
        )

    def _provider_map(self) -> dict[str, Any]:
        return {
            kind: provider
            for kind, provider in (
                ("llm", self.llm),
                ("stt", self.stt),
                ("tts", self.tts),
                ("vad", self.vad),
                ("wakeword", self.wakeword),
                ("memory", self.memory),
                ("vision", self.vision),
            )
            if provider is not None
        }

    def _providers(self) -> list[Any]:
        return list(self._provider_map().values())

    #: Without these B.O.B. cannot start at all. Everything else degrades.
    ESSENTIAL_PROVIDERS: tuple[str, ...] = ()

    async def _start_providers(self) -> None:
        """Start each provider, tolerating failures in the optional ones.

        A provider that cannot start disables the feature that depends on it and
        records why, so the UI can say "no microphone because the model is
        missing" instead of the application failing to launch.
        """
        for kind, provider in self._provider_map().items():
            try:
                await provider.start()
            except Exception as exc:
                if kind in self.ESSENTIAL_PROVIDERS:
                    raise
                self.provider_errors[kind] = str(exc)
                _log.warning("%s provider unavailable: %s", kind, exc)
                await self.bus.publish(
                    ErrorOccurred(
                        source="kernel",
                        component=f"provider.{kind}",
                        message=str(exc),
                        fatal=False,
                    )
                )

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
            "microphone": self.listening is not None,
        }
