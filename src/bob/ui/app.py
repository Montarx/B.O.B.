"""The desktop application: wiring, not logic.

Composition order matters and is the same every time:

    Settings -> KernelRuntime (own thread) -> KernelBridge -> ShellPresenter
             -> MainWindow

The window renders presenter snapshots and raises intents; the bridge turns
intents into kernel calls. Neither knows about the other's internals.
"""

from __future__ import annotations

import logging
import signal
import sys
from types import FrameType

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from bob import __identity__, __version__
from bob.config.schema import Settings
from bob.core.events import Event
from bob.ui.bridge import KernelBridge
from bob.ui.presenter import ShellPresenter
from bob.ui.runtime import KernelRuntime
from bob.ui.theme.stylesheet import build_stylesheet
from bob.ui.theme.tokens import DEFAULT_THEME, Theme
from bob.ui.viewmodel import ProviderInfo, ShellViewModel
from bob.ui.windows.main_window import MainWindow
from bob.utils import paths

_log = logging.getLogger("bob.app.ui")


def build_theme(settings: Settings) -> Theme:
    """Derive the theme from configuration."""
    theme = DEFAULT_THEME
    if settings.ui.accent:
        theme = theme.with_accent(settings.ui.accent)
    return theme.with_reduced_motion(settings.ui.reduced_motion)


class BobApplication:
    """Owns the Qt application and the kernel runtime for one session."""

    def __init__(self, settings: Settings, *, dev_tools: bool = False) -> None:
        self._settings = settings
        self._dev_tools = dev_tools
        self._theme = build_theme(settings)

        self._qt = self._build_qt_application()
        self._runtime = KernelRuntime(settings)
        self._bridge = KernelBridge(self._runtime)
        self._presenter = ShellPresenter()
        self._window = MainWindow(self._theme, dev_tools=dev_tools)

        self._telemetry = QTimer()
        self._wire()

    # -- construction ----------------------------------------------------

    def _build_qt_application(self) -> QApplication:
        # High-DPI: Qt 6 scales automatically; we only choose the rounding policy
        # so 125% and 150% Windows scaling do not produce half-pixel borders.
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication.instance() or QApplication(sys.argv)
        assert isinstance(app, QApplication)
        app.setApplicationName("B.O.B.")
        app.setApplicationDisplayName("B.O.B. — Beyond Orbit Buddy")
        app.setApplicationVersion(__version__)
        app.setOrganizationName("Montarx")
        app.setStyleSheet(build_stylesheet(self._theme))
        return app

    def _wire(self) -> None:
        # kernel -> presenter -> window
        self._bridge.eventReceived.connect(self._on_event)
        self._bridge.audioLevel.connect(self._window.set_audio_level)
        self._bridge.demoRunningChanged.connect(self._presenter.set_demo_running)
        self._presenter.set_listener(self._window.render_view_model)

        # window -> kernel
        self._window.intentRaised.connect(self._bridge.dispatch)

        # Mock telemetry until Phase 6 provides real numbers.
        from bob.dev.telemetry import MockTelemetry

        self._mock_telemetry = MockTelemetry()
        self._telemetry.setInterval(1200)
        self._telemetry.timeout.connect(self._tick_telemetry)

    # -- callbacks -------------------------------------------------------

    def _on_event(self, event: Event) -> None:
        """Runs on the GUI thread; the presenter re-renders only if it changed."""
        self._presenter.handle(event)

    def _tick_telemetry(self) -> None:
        self._presenter.set_system(self._mock_telemetry.sample())

    # -- lifecycle -------------------------------------------------------

    def run(self) -> int:
        """Start the kernel, show the window, and enter the Qt event loop."""
        paths.ensure_dirs()
        _log.info("%s v%s starting UI", __identity__, __version__)

        try:
            self._runtime.start()
        except Exception as exc:
            _log.exception("kernel failed to start")
            self._presenter.handle(_startup_error(str(exc)))
            self._window.show()
            return self._qt.exec()

        self._publish_providers()
        self._telemetry.start()

        self._window.show()
        if self._settings.app.start_minimized:
            self._window.showMinimized()

        # Ctrl+C in a terminal should close the window, not wedge the loop.
        signal.signal(signal.SIGINT, self._on_sigint)
        idle = QTimer()
        idle.start(250)
        idle.timeout.connect(lambda: None)

        try:
            return self._qt.exec()
        finally:
            self._telemetry.stop()
            self._runtime.stop()

    def _publish_providers(self) -> None:
        kernel = self._runtime.kernel
        self._presenter.set_providers(
            ProviderInfo(
                llm=getattr(kernel.llm, "name", "—"),
                stt=getattr(kernel.stt, "name", "—"),
                tts=getattr(kernel.tts, "name", "—"),
                wakeword=getattr(kernel.wakeword, "name", "—"),
                simulated=self._settings.llm.provider == "mock",
            )
        )

    def _on_sigint(self, signum: int, frame: FrameType | None) -> None:
        _log.info("interrupt received; shutting down")
        self._qt.quit()

    # -- accessors used by tests ----------------------------------------

    @property
    def window(self) -> MainWindow:
        return self._window

    @property
    def presenter(self) -> ShellPresenter:
        return self._presenter

    @property
    def view_model(self) -> ShellViewModel:
        return self._presenter.view_model


def _startup_error(message: str) -> Event:
    from bob.core.events import ErrorOccurred

    return ErrorOccurred(source="ui", component="kernel", message=message, fatal=True)
