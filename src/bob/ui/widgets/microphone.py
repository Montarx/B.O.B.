"""The listen control.

Temporary infrastructure: until the wake word arrives in Phase 5, this button and
its shortcut are how listening is triggered. The pipeline behind it is the real
one, so nothing here is throwaway except the trigger itself.

Like every widget, it renders state and emits an intent. It has no idea a
microphone exists — it cannot open a device even if it wanted to.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from bob.core.states import BobState
from bob.ui.theme.color import parse_hex
from bob.ui.theme.tokens import Theme
from bob.ui.viewmodel import MicrophoneInfo
from bob.ui.widgets.primitives import Label, repolish

#: Greek labels, matching the tone of the rest of the interface.
LABEL_IDLE = "Άκου με"
LABEL_LISTENING = "Σταμάτα"
LABEL_BUSY = "Περίμενε…"
LABEL_UNAVAILABLE = "Χωρίς μικρόφωνο"


class MicIcon(QWidget):
    """A small drawn microphone glyph.

    Painted rather than shipped as an asset: it is a dozen lines of geometry, it
    inherits the accent colour for free, and it avoids adding a binary icon set
    to the repository for one symbol.
    """

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._color = theme.palette.ink.secondary
        self.setFixedSize(theme.icon.md, theme.icon.md)

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r, g, b = parse_hex(self._color)
        pen = QPen(QColor(r, g, b), 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        w, h = self.width(), self.height()
        capsule_w = w * 0.34
        capsule_h = h * 0.46
        painter.drawRoundedRect(
            QRectF((w - capsule_w) / 2, h * 0.12, capsule_w, capsule_h),
            capsule_w / 2,
            capsule_w / 2,
        )
        # The cradle arc and stem.
        painter.drawArc(
            int(w * 0.22),
            int(h * 0.34),
            int(w * 0.56),
            int(h * 0.46),
            180 * 16,
            180 * 16,
        )
        painter.drawLine(int(w / 2), int(h * 0.80), int(w / 2), int(h * 0.92))


class MicrophoneButton(QWidget):
    """Start/stop listening, with a status line underneath."""

    toggled = Signal(bool)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._listening = False
        self._enabled = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.space.sm)

        self._button = QPushButton(LABEL_IDLE)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setAccessibleName("Ενεργοποίηση μικροφώνου")
        self._button.setToolTip("Άκου με (Ctrl+Space)")
        self._button.clicked.connect(self._on_click)
        self._icon = MicIcon(theme, self._button)

        icon_row = QHBoxLayout(self._button)
        icon_row.setContentsMargins(theme.space.md, 0, theme.space.md, 0)
        icon_row.setSpacing(theme.space.sm)
        icon_row.addWidget(self._icon)
        icon_row.addStretch(1)

        row.addWidget(self._button)

        self._status = Label("", theme, "caption")
        self._status.set_tone("muted")
        self._status.setWordWrap(True)
        row.addWidget(self._status, 1)

    # -- rendering -------------------------------------------------------

    def render_state(
        self, state: BobState, microphone: MicrophoneInfo, *, can_listen: bool
    ) -> None:
        """Update from a snapshot. The widget decides nothing about audio."""
        palette = self._theme.palette
        self._listening = microphone.listening
        self._enabled = can_listen and (microphone.available or not microphone.error)

        if microphone.error:
            self._button.setText(LABEL_UNAVAILABLE)
            self._button.setEnabled(False)
            self._icon.set_color(palette.status.error)
            self._status.setText(microphone.error)
            self._status.set_tone("error")
        elif microphone.listening:
            self._button.setText(LABEL_LISTENING)
            self._button.setEnabled(True)
            self._icon.set_color(palette.status.listening)
            self._status.setText(microphone.device)
            self._status.set_tone("muted")
        elif state is BobState.TRANSCRIBING:
            self._button.setText(LABEL_BUSY)
            self._button.setEnabled(False)
            self._icon.set_color(palette.status.transcribing)
            self._status.setText("Μεταγράφω…")
            self._status.set_tone("muted")
        else:
            self._button.setText(LABEL_IDLE)
            self._button.setEnabled(can_listen)
            self._icon.set_color(palette.ink.secondary if can_listen else palette.ink.disabled)
            self._status.setText(microphone.device)
            self._status.set_tone("muted")

        self._button.setProperty("selected", "true" if microphone.listening else "false")
        repolish(self._button)

    @property
    def listening(self) -> bool:
        return self._listening

    def _on_click(self) -> None:
        self.toggled.emit(not self._listening)
