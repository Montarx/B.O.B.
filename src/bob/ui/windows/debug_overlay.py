"""Developer state switcher.

**Not part of the production interface.** It appears only when B.O.B. is started
with ``--dev`` (or ``BOB__UI__DEV_TOOLS=true``), and is toggled with F12.

It does not force states. Pressing a state button emits a
:class:`RequestState` intent; the bridge then walks a *legal* path through the
transition table to get there. The Phase 0 invariant — that no illegal
transition ever happens — holds even in dev mode.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bob.core.states import BobState
from bob.ui.theme.tokens import Theme
from bob.ui.visual import VisualCatalogue
from bob.ui.widgets.primitives import Divider, Label, repolish

_COLUMNS = 2


class DebugOverlay(QWidget):
    """A floating panel of state buttons plus demo controls."""

    stateRequested = Signal(BobState)
    demoToggled = Signal(bool)
    conversationCleared = Signal()

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._catalogue = VisualCatalogue(theme)
        self._buttons: dict[BobState, QPushButton] = {}
        self._demo_running = False

        self.setProperty("role", "debugOverlay")
        self.setAutoFillBackground(True)
        self.setAccessibleName("Developer state switcher")

        column = QVBoxLayout(self)
        column.setContentsMargins(theme.space.lg, theme.space.md, theme.space.lg, theme.space.md)
        column.setSpacing(theme.space.sm)

        header = QHBoxLayout()
        header.setSpacing(theme.space.sm)
        title = Label("DEV // STATE", theme, "panelHeader")
        title.set_tone("accent")
        header.addWidget(title)
        header.addStretch(1)
        self._fps = Label("", theme, "data")
        self._fps.set_tone("muted")
        header.addWidget(self._fps)
        column.addLayout(header)
        column.addWidget(Divider(theme))

        grid = QGridLayout()
        grid.setSpacing(theme.space.xs)
        for index, state in enumerate(BobState):
            button = QPushButton(state.value)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"Μετάβαση σε {state.value} (νόμιμη διαδρομή)")
            button.clicked.connect(lambda _checked=False, s=state: self.stateRequested.emit(s))
            self._buttons[state] = button
            grid.addWidget(button, index // _COLUMNS, index % _COLUMNS)
        column.addLayout(grid)

        column.addWidget(Divider(theme))

        controls = QHBoxLayout()
        controls.setSpacing(theme.space.sm)
        self._demo = QPushButton("▶  Demo")
        self._demo.setToolTip("Παίξε το πλήρες σενάριο (F9)")
        self._demo.clicked.connect(self._toggle_demo)
        controls.addWidget(self._demo)

        clear = QPushButton("Καθάρισε")
        clear.setProperty("variant", "ghost")
        clear.clicked.connect(self.conversationCleared.emit)
        controls.addWidget(clear)
        column.addLayout(controls)

        hint = Label("F12 κρύβει · F9 demo", theme, "caption")
        hint.set_tone("muted")
        column.addWidget(hint)

        self.setFixedWidth(268)

    # -- state -----------------------------------------------------------

    def set_state(self, state: BobState) -> None:
        """Highlight the state B.O.B. is actually in."""
        for candidate, button in self._buttons.items():
            selected = candidate is state
            button.setProperty("selected", "true" if selected else "false")
            repolish(button)

    def set_fps(self, fps: int) -> None:
        self._fps.setText(f"{fps} fps")

    def set_demo_running(self, running: bool) -> None:
        self._demo_running = running
        self._demo.setText("■  Stop" if running else "▶  Demo")

    def _toggle_demo(self) -> None:
        self.demoToggled.emit(not self._demo_running)
