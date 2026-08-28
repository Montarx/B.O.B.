"""Window chrome: the wordmark bar, the compact status strip, and the input bar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bob.core.states import BobState
from bob.ui.theme.fonts import apply_font
from bob.ui.theme.tokens import Theme
from bob.ui.visual import VisualCatalogue
from bob.ui.widgets.primitives import Divider, Label, StatusDot

#: States during which a pulsing status dot is meaningful.
_PULSING = {
    BobState.WAKE_DETECTED,
    BobState.LISTENING,
    BobState.TRANSCRIBING,
    BobState.THINKING,
    BobState.EXECUTING,
    BobState.SPEAKING,
}


class Wordmark(QWidget):
    """B.O.B. / BEYOND ORBIT BUDDY — the brand lockup.

    Two lines, tight leading, wide tracking on both. This is the only place in
    the interface that uses the display type roles.
    """

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        name = Label("B.O.B.", theme, "wordmark")
        tagline = Label("Beyond Orbit Buddy", theme, "tagline")
        column.addWidget(name)
        column.addWidget(tagline)
        self.setAccessibleName("B.O.B. — Beyond Orbit Buddy")


class StatusStrip(QWidget):
    """Compact state readout for the title bar: a dot and one word."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._catalogue = VisualCatalogue(theme)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.space.md, theme.space.xs, theme.space.md, theme.space.xs)
        row.setSpacing(theme.space.sm)
        self.setProperty("role", "chip")

        self._dot = StatusDot(theme, size=8)
        self._label = Label("CORE // OFFLINE", theme, "status")
        row.addWidget(self._dot)
        row.addWidget(self._label)

    def set_state(self, state: BobState, status_text: str) -> None:
        colour = self._catalogue.accent_for(state)
        self._dot.set_color(colour)
        self._dot.set_pulse(state in _PULSING)
        self._label.setText(status_text)
        self._label.setStyleSheet(f"color: {colour};")
        self.setAccessibleDescription(f"Κατάσταση: {status_text}")


class TitleBar(QWidget):
    """Top bar: wordmark on the left, status on the right."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "titlebar")
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.space.xl, theme.space.md, theme.space.xl, theme.space.md)
        row.setSpacing(theme.space.lg)

        row.addWidget(Wordmark(theme))
        row.addStretch(1)
        self._status = StatusStrip(theme)
        row.addWidget(self._status)

    def set_state(self, state: BobState, status_text: str) -> None:
        self._status.set_state(state, status_text)


class InputBar(QWidget):
    """Text entry.

    Present from Phase 1 so B.O.B. is usable before the microphone exists, and
    permanently useful afterwards — typing is often better than talking.
    """

    submitted = Signal(str)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.space.sm)

        self._field = QLineEdit()
        self._field.setPlaceholderText("Γράψε στον B.O.B.…")
        self._field.setClearButtonEnabled(True)
        self._field.setAccessibleName("Μήνυμα προς τον B.O.B.")
        apply_font(self._field, theme, theme.type.body)
        self._field.returnPressed.connect(self._submit)
        row.addWidget(self._field, 1)

        self._send = QPushButton("Στείλε")
        self._send.setProperty("variant", "primary")
        self._send.setAccessibleName("Αποστολή μηνύματος")
        self._send.setDefault(True)
        self._send.clicked.connect(self._submit)
        row.addWidget(self._send)

        self.setFocusProxy(self._field)

    def _submit(self) -> None:
        text = self._field.text().strip()
        if not text:
            return
        self._field.clear()
        self.submitted.emit(text)

    def set_enabled_state(self, enabled: bool) -> None:
        """Disable input while B.O.B. is mid-thought, without losing focus."""
        self._field.setEnabled(enabled)
        self._send.setEnabled(enabled)


class CaptionLine(QWidget):
    """The Greek line under the core: "Σε ακούω...", "Σκέφτομαι...".

    Sits directly beneath the orb and is the main thing a user reads, so it uses
    the title role rather than a caption size.
    """

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._catalogue = VisualCatalogue(theme)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.space.xs)

        self._caption = Label("", theme, "title")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setWordWrap(True)
        column.addWidget(self._caption)

        self._status = Label("", theme, "status")
        self._status.set_tone("muted")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self._status)

        # A live region: screen readers should announce state changes.
        self.setAccessibleName("Κατάσταση B.O.B.")

    def set_state(self, state: BobState, caption: str, status_text: str) -> None:
        self._caption.setText(caption)
        self._status.setText(status_text)
        self._status.setStyleSheet(f"color: {self._catalogue.accent_for(state)};")
        self.setAccessibleDescription(f"{status_text}. {caption}")


__all__ = ["CaptionLine", "Divider", "InputBar", "StatusStrip", "TitleBar", "Wordmark"]
