"""Reusable building blocks.

Every panel in B.O.B. is composed from these. Nothing here styles itself with a
literal colour or size — appearance comes from the theme, applied through
dynamic properties that :mod:`bob.ui.theme.stylesheet` selects on.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bob.ui.theme.color import parse_hex
from bob.ui.theme.fonts import apply_font
from bob.ui.theme.tokens import Theme


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed.

    Qt does not re-evaluate property selectors on its own, so every place that
    flips a ``[state=...]`` property must call this.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_glow(widget: QWidget, theme: Theme, color: str, level: str) -> None:
    """Attach the themed glow budget to a widget, or remove it for ``none``."""
    radius, alpha = theme.glow.level(level)
    if radius <= 0 or alpha <= 0.0:
        widget.setGraphicsEffect(None)  # type: ignore[arg-type]
        return
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(radius)
    effect.setOffset(0, 0)
    r, g, b = parse_hex(color)
    effect.setColor(QColor(r, g, b, int(alpha * 255)))
    widget.setGraphicsEffect(effect)


class Label(QLabel):
    """A label bound to a typographic role."""

    def __init__(
        self,
        text: str,
        theme: Theme,
        role: str = "body",
        *,
        tone: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        font_role = getattr(theme.type, _ROLE_ATTR.get(role, "body"))
        apply_font(self, theme, font_role, type_name=role)
        if tone:
            self.setProperty("tone", tone)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        repolish(self)


_ROLE_ATTR = {
    "wordmark": "wordmark",
    "tagline": "tagline",
    "title": "title",
    "panelHeader": "panel_header",
    "body": "body",
    "bodyStrong": "body_strong",
    "caption": "caption",
    "status": "status",
    "metric": "metric",
    "data": "data",
}


class Divider(QFrame):
    """A hairline rule."""

    def __init__(
        self, theme: Theme, *, vertical: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", "divider")
        if vertical:
            self.setProperty("vertical", "true")
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)


class StatusDot(QWidget):
    """A small filled circle used to signal state in compact places.

    Drawn rather than styled because QSS cannot render a soft ring, and because
    a 10px painted dot is cheaper than a styled widget with an effect.
    """

    def __init__(self, theme: Theme, *, size: int = 10, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._color = theme.palette.status.offline
        self._pulse = False
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self.update()

    def set_pulse(self, pulse: bool) -> None:
        if pulse != self._pulse:
            self._pulse = pulse
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r, g, b = parse_hex(self._color)
        rect = self.rect()
        centre = rect.center()

        if self._pulse:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(r, g, b, 60))
            painter.drawEllipse(centre, rect.width() / 2, rect.height() / 2)

        painter.setBrush(QColor(r, g, b, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        inner = rect.width() / 2 - (2 if self._pulse else 0)
        painter.drawEllipse(centre, inner, inner)


class Meter(QWidget):
    """A slim horizontal bar for CPU/RAM/disk.

    Deliberately not a chart: the brief asks for calm, not fifty graphs.
    """

    def __init__(self, theme: Theme, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._value = 0.0
        self._color = theme.palette.accent
        self.setFixedHeight(3)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.004:
            self._value = value
            self.update()

    def set_color(self, color: str) -> None:
        if color != self._color:
            self._color = color
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        radius = rect.height() / 2

        tr, tg, tb = parse_hex(self._theme.palette.line.subtle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tr, tg, tb))
        painter.drawRoundedRect(rect, radius, radius)

        if self._value <= 0.0:
            return
        filled = rect.adjusted(0, 0, -int(rect.width() * (1.0 - self._value)), 0)
        r, g, b = parse_hex(self._color)
        painter.setBrush(QColor(r, g, b))
        painter.drawRoundedRect(filled, radius, radius)


class Panel(QFrame):
    """The standard container: optional header, then a content area.

    All panels share one shape, one border and one spacing rhythm, which is what
    makes the interface read as a system rather than as assorted widgets.
    """

    def __init__(
        self,
        theme: Theme,
        title: str = "",
        *,
        flat: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setProperty("role", "panel")
        if flat:
            self.setProperty("flat", "true")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.space.lg, theme.space.md, theme.space.lg, theme.space.md)
        outer.setSpacing(theme.space.sm)

        self._header_row: QHBoxLayout | None = None
        if title:
            self._header_row = QHBoxLayout()
            self._header_row.setContentsMargins(0, 0, 0, 0)
            self._header_row.setSpacing(theme.space.sm)
            self._title = Label(title, theme, "panelHeader")
            self._header_row.addWidget(self._title)
            self._header_row.addStretch(1)
            outer.addLayout(self._header_row)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(theme.space.sm)
        outer.addLayout(self._body, 1)

    @property
    def body(self) -> QVBoxLayout:
        """Layout for panel content."""
        return self._body

    def add_header_widget(self, widget: QWidget) -> None:
        """Put a widget on the right-hand side of the panel header."""
        if self._header_row is not None:
            self._header_row.addWidget(widget)

    def set_emphasis(self, emphasis: bool) -> None:
        self.setProperty("emphasis", "true" if emphasis else "false")
        repolish(self)


class Stage(QFrame):
    """The recessed well the core sits in."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "stage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.space.lg, theme.space.lg, theme.space.lg, theme.space.lg)
        layout.setSpacing(theme.space.sm)
        self._layout = layout

    @property
    def body(self) -> QVBoxLayout:
        return self._layout
