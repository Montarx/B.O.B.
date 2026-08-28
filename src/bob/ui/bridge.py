"""The one file that imports both Qt and the kernel.

Everything else obeys the fence: ``src/bob/ui/`` may import the kernel, and the
kernel may never import Qt. This module is the door between them, in both
directions.

**Kernel to UI.** The bridge subscribes to the event bus. Those callbacks run on
the kernel thread, so they do nothing but emit a Qt signal. Because the bridge
object lives on the GUI thread, Qt automatically makes those connections queued,
which is the supported way to cross threads.

**UI to kernel.** Intents arrive from widgets and become coroutines submitted to
the kernel loop.

High-frequency audio levels get their own signal so they can be routed straight
to the core animation, instead of pushing a full view-model diff 30 times a
second.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from bob.core.events import AudioLevel, Event, TranscriptReady
from bob.core.states import BobState, find_transition_path
from bob.ui.intents import (
    CancelCurrent,
    ConfirmAction,
    Intent,
    RequestState,
    RunDemo,
    SubmitText,
    ToggleListening,
)
from bob.ui.runtime import KernelRuntime

if TYPE_CHECKING:
    from bob.dev.scenarios import DemoScenario

_log = logging.getLogger("bob.app.bridge")


class KernelBridge(QObject):
    """Marshals events onto the GUI thread and intents onto the kernel thread."""

    #: Any event other than audio level; carries the Event object.
    eventReceived = Signal(object)
    #: Audio level, routed straight to the core: (rms 0..1, "input"|"output").
    audioLevel = Signal(float, str)
    #: Emitted when a demo scenario starts or stops.
    demoRunningChanged = Signal(bool)

    def __init__(self, runtime: KernelRuntime, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._demo: DemoScenario | None = None
        runtime.bus.subscribe("*", self._on_event)

    # -- kernel -> UI ----------------------------------------------------

    async def _on_event(self, event: Event) -> None:
        """Runs on the kernel thread. Emit and return; never do work here."""
        if isinstance(event, AudioLevel):
            self.audioLevel.emit(float(event.rms), event.direction)
            return
        self.eventReceived.emit(event)

    # -- UI -> kernel ----------------------------------------------------

    def dispatch(self, intent: Intent) -> None:
        """Translate a UI intent into kernel work."""
        match intent:
            case SubmitText(text=text):
                self._runtime.call_soon(self._submit_text(text))
            case RequestState(state=state):
                self._runtime.call_soon(self._goto_state(state))
            case RunDemo(running=running):
                self._toggle_demo(running)
            case ConfirmAction():
                # Wired to PermissionBroker in Phase 6, when real tools exist.
                _log.debug("confirmation intent ignored in Phase 1")
            case ToggleListening(listening=listening):
                self._runtime.call_soon(self._toggle_listening(listening))
            case CancelCurrent():
                self._runtime.call_soon(self._goto_state(BobState.IDLE))

    async def _submit_text(self, text: str) -> None:
        """Phase 1: typed input is echoed as a transcript so the UI can render it.

        Phase 3 replaces this with a real turn through the orchestrator.
        """
        await self._runtime.bus.publish(TranscriptReady(source="ui", text=text, language="el"))

    async def _toggle_listening(self, listening: bool) -> None:
        """Open or close the microphone via the kernel's pipeline."""
        pipeline = self._runtime.kernel.listening
        if pipeline is None:
            from bob.core.events import AudioDeviceErrorEvent

            await self._runtime.bus.publish(
                AudioDeviceErrorEvent(
                    source="ui",
                    message=(
                        "Audio capture is unavailable. Install the voice extra: "
                        'pip install -e ".[voice]"'
                    ),
                )
            )
            return
        if listening:
            await pipeline.start_listening()
        else:
            await pipeline.stop_listening(reason="user stopped")

    async def _goto_state(self, target: BobState) -> None:
        """Walk a *legal* path to ``target``.

        The debug switcher must not be able to violate the transition table —
        that invariant is the whole point of having one. Instead of forcing the
        state, we find a valid route and take it.
        """
        machine = self._runtime.kernel.state
        path = find_transition_path(machine.state, target)
        if path is None:
            _log.warning("no legal path from %s to %s", machine.state, target)
            return
        for step in path:
            await machine.transition(step, reason="debug")

    # -- demo ------------------------------------------------------------

    def _toggle_demo(self, running: bool) -> None:
        from bob.dev.scenarios import DemoScenario

        if running:
            if self._demo is not None:
                return
            scenario = DemoScenario(self._runtime.kernel)
            self._demo = scenario
            self._runtime.call_soon(self._run_demo(scenario))
            self.demoRunningChanged.emit(True)
        elif self._demo is not None:
            self._demo.stop()

    async def _run_demo(self, scenario: DemoScenario) -> None:
        try:
            await scenario.run()
        finally:
            self._demo = None
            self.demoRunningChanged.emit(False)

    @property
    def demo_running(self) -> bool:
        return self._demo is not None
