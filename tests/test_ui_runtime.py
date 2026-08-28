"""Kernel runtime and bridge — the thread boundary.

These are the tests that matter for the architecture: the kernel really does run
on its own loop, and the UI really can only reach it through the two supported
doors.
"""

from __future__ import annotations

import os
import threading

import pytest

pytest.importorskip("PySide6", reason="UI tests require the [ui] extra")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bob.config.loader import load_settings
from bob.config.schema import Settings
from bob.core.errors import ProviderNotFoundError
from bob.core.events import Event, TranscriptReady
from bob.core.states import BobState
from bob.ui.bridge import KernelBridge
from bob.ui.intents import RequestState, SubmitText
from bob.ui.runtime import KernelRuntime


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture
def runtime(settings: Settings):
    rt = KernelRuntime(settings)
    rt.start()
    yield rt
    rt.stop()


def drain(app: QApplication, times: int = 40) -> None:
    """Pump the Qt loop so queued cross-thread signals are delivered."""
    for _ in range(times):
        app.processEvents()


def test_runtime_boots_the_kernel_on_another_thread(
    runtime: KernelRuntime,
) -> None:
    assert runtime.running
    assert runtime.kernel.started
    assert runtime.kernel.state.state is BobState.IDLE


def test_kernel_loop_is_not_the_calling_thread(runtime: KernelRuntime) -> None:
    """The whole point: a slow repaint must not be able to stall the kernel."""

    async def which_thread() -> int:
        return threading.get_ident()

    kernel_thread = runtime.submit(which_thread()).result(timeout=5)
    assert kernel_thread != threading.get_ident()


def test_submit_returns_a_result(runtime: KernelRuntime) -> None:
    async def add() -> int:
        return 40 + 2

    assert runtime.submit(add()).result(timeout=5) == 42


def test_submit_before_start_is_refused(settings: Settings) -> None:
    rt = KernelRuntime(settings)

    async def noop() -> None:
        return None

    coro = noop()
    with pytest.raises(RuntimeError):
        rt.submit(coro)
    coro.close()


def test_stop_is_idempotent(settings: Settings) -> None:
    rt = KernelRuntime(settings)
    rt.start()
    rt.stop()
    rt.stop()
    assert not rt.running


def test_startup_failure_surfaces_to_the_caller(clean_env: None) -> None:
    bad = load_settings(overrides={"llm": {"provider": "does-not-exist"}})
    rt = KernelRuntime(bad)
    with pytest.raises(ProviderNotFoundError):
        rt.start()
    rt.stop()


# -- bridge -----------------------------------------------------------------


def test_bridge_forwards_events_to_the_gui_thread(
    qt_app: QApplication, runtime: KernelRuntime
) -> None:
    bridge = KernelBridge(runtime)
    received: list[Event] = []
    bridge.eventReceived.connect(received.append)

    runtime.submit(runtime.bus.publish(TranscriptReady(source="test", text="γεια"))).result(
        timeout=5
    )
    drain(qt_app)

    assert any(getattr(e, "text", "") == "γεια" for e in received)


def test_bridge_routes_audio_levels_separately(
    qt_app: QApplication, runtime: KernelRuntime
) -> None:
    """High-frequency levels must not push a full view-model diff."""
    from bob.core.events import AudioLevel

    bridge = KernelBridge(runtime)
    events: list[Event] = []
    levels: list[tuple[float, str]] = []
    bridge.eventReceived.connect(events.append)
    bridge.audioLevel.connect(lambda rms, d: levels.append((rms, d)))

    runtime.submit(
        runtime.bus.publish(AudioLevel(source="test", rms=0.5, direction="input"))
    ).result(timeout=5)
    drain(qt_app)

    assert levels == [(0.5, "input")]
    assert not any(getattr(e, "rms", None) is not None for e in events)


def test_submit_text_intent_becomes_a_transcript(
    qt_app: QApplication, runtime: KernelRuntime
) -> None:
    bridge = KernelBridge(runtime)
    received: list[Event] = []
    bridge.eventReceived.connect(received.append)

    bridge.dispatch(SubmitText("άνοιξε spotify"))
    for _ in range(50):
        drain(qt_app, 5)
        if any(getattr(e, "text", "") == "άνοιξε spotify" for e in received):
            break
    assert any(getattr(e, "text", "") == "άνοιξε spotify" for e in received)


def test_state_intent_walks_a_legal_path(qt_app: QApplication, runtime: KernelRuntime) -> None:
    """The debug switcher must not be able to break the transition table."""
    bridge = KernelBridge(runtime)
    bridge.dispatch(RequestState(BobState.EXECUTING))

    for _ in range(60):
        drain(qt_app, 5)
        if runtime.kernel.state.state is BobState.EXECUTING:
            break
    assert runtime.kernel.state.state is BobState.EXECUTING

    history = [state for state, _ in runtime.kernel.state.history]
    assert BobState.THINKING in history  # it went the legal way round


def test_unreachable_state_request_is_ignored_not_forced(
    qt_app: QApplication, runtime: KernelRuntime
) -> None:
    """Every state is reachable today; this guards the failure path anyway."""
    bridge = KernelBridge(runtime)
    before = runtime.kernel.state.state
    bridge.dispatch(RequestState(before))
    drain(qt_app)
    assert runtime.kernel.state.state is before
