"""The main B.O.B. window.

Assembles the shell from panels and renders :class:`ShellViewModel` snapshots.
It contains layout and wiring — no business logic: every user action leaves as
an :mod:`bob.ui.intents` intent, and every change arrives as a snapshot.

Layout is three columns at the design width, degrading by
:mod:`bob.ui.responsive` rules rather than by absolute positioning.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bob.ui.intents import Intent, RequestState, RunDemo, SubmitText, ToggleListening
from bob.ui.responsive import ShellLayout, core_diameter, layout_for_width
from bob.ui.theme.tokens import Theme
from bob.ui.viewmodel import ShellViewModel
from bob.ui.widgets.chrome import CaptionLine, InputBar, TitleBar
from bob.ui.widgets.conversation import ConversationView
from bob.ui.widgets.core_view import CoreView
from bob.ui.widgets.microphone import MicrophoneButton
from bob.ui.widgets.panels import (
    ActivityPanel,
    ProviderPanel,
    SystemPanel,
    TaskPanel,
)
from bob.ui.widgets.primitives import Label, Panel, Stage
from bob.ui.windows.debug_overlay import DebugOverlay

_log = logging.getLogger("bob.app.window")


class MainWindow(QWidget):
    """B.O.B.'s shell."""

    #: Emitted for everything the user does. The application wires this to the
    #: bridge; the window itself never touches the kernel.
    intentRaised = Signal(object)

    def __init__(
        self, theme: Theme, *, dev_tools: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._dev_tools = dev_tools
        self._layout_spec: ShellLayout | None = None
        self._vm = ShellViewModel()

        self.setProperty("role", "root")
        self.setWindowTitle("B.O.B. — Beyond Orbit Buddy")
        self.setMinimumSize(960, 640)
        self.resize(1600, 960)

        self._build()
        self._build_shortcuts()
        self._apply_layout(layout_for_width(self.width()))
        self._render_all(self._vm)

    # -- construction ----------------------------------------------------

    def _build(self) -> None:
        theme = self._theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._titlebar = TitleBar(theme)
        root.addWidget(self._titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(theme.space.xl, theme.space.lg, theme.space.xl, theme.space.xl)
        body.setSpacing(theme.space.lg)
        root.addLayout(body, 1)

        self._left_rail = self._build_left_rail()
        self._centre = self._build_centre()
        self._right_rail = self._build_right_rail()

        body.addWidget(self._left_rail)
        body.addWidget(self._centre, 1)
        body.addWidget(self._right_rail)

        self._debug = DebugOverlay(theme, self) if self._dev_tools else None
        if self._debug is not None:
            self._debug.stateRequested.connect(
                lambda state: self.intentRaised.emit(RequestState(state))
            )
            self._debug.demoToggled.connect(
                lambda running: self.intentRaised.emit(RunDemo(running))
            )
            self._debug.conversationCleared.connect(self._clear_conversation)
            self._core.fpsChanged.connect(self._debug.set_fps)
            self._debug.hide()

    def _build_left_rail(self) -> QWidget:
        theme = self._theme
        rail = QWidget()
        column = QVBoxLayout(rail)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.space.lg)

        self._task_panel = TaskPanel(theme)
        self._activity_panel = ActivityPanel(theme)
        column.addWidget(self._task_panel)
        column.addWidget(self._activity_panel, 1)
        return rail

    def _build_centre(self) -> QWidget:
        theme = self._theme
        centre = QWidget()
        column = QVBoxLayout(centre)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.space.lg)

        # The core sits in a recessed stage; it is the hero of the screen.
        self._stage = Stage(theme)
        self._core = CoreView(theme)
        self._core.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._caption = CaptionLine(theme)
        self._stage.body.addWidget(self._core, 1)
        self._stage.body.addWidget(self._caption)

        # Live transcript, shown under the core while STT is decoding.
        self._partial = Label("", theme, "body")
        self._partial.set_tone("muted")
        self._partial.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._partial.setWordWrap(True)
        self._partial.hide()
        self._stage.body.addWidget(self._partial)
        column.addWidget(self._stage, 3)

        conversation_panel = Panel(theme, "ΣΥΝΟΜΙΛΙΑ")
        self._conversation = ConversationView(theme)
        conversation_panel.body.addWidget(self._conversation, 1)
        column.addWidget(conversation_panel, 2)

        self._error = Label("", theme, "caption")
        self._error.set_tone("error")
        self._error.setWordWrap(True)
        self._error.hide()
        column.addWidget(self._error)

        # The listen control sits with the input, because in Phase 2 those are
        # the two ways to talk to B.O.B.
        self._microphone = MicrophoneButton(theme)
        self._microphone.toggled.connect(
            lambda listening: self.intentRaised.emit(ToggleListening(listening))
        )
        column.addWidget(self._microphone)

        self._input = InputBar(theme)
        self._input.submitted.connect(lambda text: self.intentRaised.emit(SubmitText(text)))
        column.addWidget(self._input)
        return centre

    def _build_right_rail(self) -> QWidget:
        theme = self._theme
        rail = QWidget()
        column = QVBoxLayout(rail)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.space.lg)

        self._system_panel = SystemPanel(theme)
        self._provider_panel = ProviderPanel(theme)
        column.addWidget(self._system_panel)
        column.addWidget(self._provider_panel)
        column.addStretch(1)
        return rail

    def _build_shortcuts(self) -> None:
        if self._dev_tools:
            QShortcut(QKeySequence("F12"), self, self._toggle_debug)
            QShortcut(QKeySequence("F9"), self, self._toggle_demo)
        QShortcut(QKeySequence("Ctrl+L"), self, self._clear_conversation)
        # Focus the input from anywhere, so B.O.B. is keyboard-first.
        QShortcut(QKeySequence("Ctrl+K"), self, lambda: self._input.setFocus())
        # Push-to-listen until the wake word exists.
        QShortcut(QKeySequence("Ctrl+Space"), self, self._toggle_listening)

    # -- rendering -------------------------------------------------------

    def _render_all(self, vm: ShellViewModel) -> None:
        """Unconditional first paint.

        ``render`` diffs against the previous snapshot, so the very first one —
        which is equal to the default — would update nothing and leave panels
        showing their unconfigured state. This primes every widget once.
        """
        self._vm = vm
        self._titlebar.set_state(vm.state, vm.status_text)
        self._core.set_state(vm.state)
        self._caption.set_state(vm.state, vm.caption, vm.status_text)
        self._conversation.set_entries(vm.conversation)
        self._activity_panel.set_actions(vm.actions)
        self._task_panel.set_task(vm.task)
        self._system_panel.set_stats(vm.system)
        self._provider_panel.set_providers(vm.providers)
        self._input.set_enabled_state(vm.input_enabled)
        self._microphone.render_state(vm.state, vm.microphone, can_listen=vm.can_listen)
        self._partial.setVisible(bool(vm.partial_transcript))
        self._error.setVisible(bool(vm.error))
        if self._debug is not None:
            self._debug.set_state(vm.state)

    def render_view_model(self, vm: ShellViewModel) -> None:
        """Apply a view-model snapshot. Cheap when little changed."""
        previous, self._vm = self._vm, vm

        if vm.state is not previous.state or vm.status_text != previous.status_text:
            self._titlebar.set_state(vm.state, vm.status_text)
            self._core.set_state(vm.state)
            if self._debug is not None:
                self._debug.set_state(vm.state)

        if vm.caption != previous.caption or vm.state is not previous.state:
            self._caption.set_state(vm.state, vm.caption, vm.status_text)

        if vm.conversation != previous.conversation:
            self._conversation.set_entries(vm.conversation)
        if vm.actions != previous.actions:
            self._activity_panel.set_actions(vm.actions)
        if vm.task != previous.task:
            self._task_panel.set_task(vm.task)
        if vm.system != previous.system:
            self._system_panel.set_stats(vm.system)
        if vm.providers != previous.providers:
            self._provider_panel.set_providers(vm.providers)
        if vm.input_enabled != previous.input_enabled:
            self._input.set_enabled_state(vm.input_enabled)
        if vm.microphone != previous.microphone or vm.state is not previous.state:
            self._microphone.render_state(vm.state, vm.microphone, can_listen=vm.can_listen)
        if vm.partial_transcript != previous.partial_transcript:
            self._partial.setText(vm.partial_transcript)
            self._partial.setVisible(bool(vm.partial_transcript))
        if vm.error != previous.error:
            self._error.setText(vm.error)
            self._error.setVisible(bool(vm.error))
        if vm.demo_running != previous.demo_running and self._debug is not None:
            self._debug.set_demo_running(vm.demo_running)

    def set_audio_level(self, level: float, direction: str) -> None:
        """Route an audio level straight to the core, bypassing the view model."""
        self._core.set_level(level)

    # -- responsive ------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_layout(layout_for_width(self.width()))
        self._position_debug()

    def _apply_layout(self, spec: ShellLayout) -> None:
        if spec == self._layout_spec:
            self._resize_core()
            return
        self._layout_spec = spec

        self._left_rail.setVisible(spec.show_left_rail)
        self._right_rail.setVisible(spec.show_right_rail)
        if spec.show_left_rail:
            self._left_rail.setFixedWidth(spec.left_rail_width)
        if spec.show_right_rail:
            self._right_rail.setFixedWidth(spec.right_rail_width)
        self._centre.setMaximumWidth(spec.center_max_width)
        self._resize_core()

    def _resize_core(self) -> None:
        if self._layout_spec is None:
            return
        available = min(self._stage.width(), self._stage.height())
        if available > 0:
            self._core.set_diameter(core_diameter(available, self._layout_spec))

    # -- dev tooling -----------------------------------------------------

    def _toggle_debug(self) -> None:
        if self._debug is None:
            return
        self._debug.setVisible(not self._debug.isVisible())
        self._position_debug()

    def _toggle_demo(self) -> None:
        self.intentRaised.emit(RunDemo(not self._vm.demo_running))

    def _toggle_listening(self) -> None:
        if self._vm.can_listen or self._vm.microphone.listening:
            self.intentRaised.emit(ToggleListening(not self._vm.microphone.listening))

    def _position_debug(self) -> None:
        if self._debug is None or not self._debug.isVisible():
            return
        margin = self._theme.space.xl
        self._debug.adjustSize()
        self._debug.move(
            self.width() - self._debug.width() - margin,
            self._titlebar.height() + margin,
        )
        self._debug.raise_()

    def _clear_conversation(self) -> None:
        self._conversation.set_entries(())
        self._activity_panel.set_actions(())

    # -- convenience for the application object --------------------------

    def emit_intent(self, intent: Intent) -> None:
        self.intentRaised.emit(intent)

    @property
    def core(self) -> CoreView:
        return self._core

    @property
    def debug_overlay(self) -> DebugOverlay | None:
        return self._debug
