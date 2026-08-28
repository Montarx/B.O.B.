"""The conversation / activity stream.

Deliberately not a chat client. Speech, tool calls and system notes share one
chronological column, distinguished by a **gutter mark** rather than by chat
bubbles: a thin accent rule for B.O.B., a dim rule for the user, a small glyph
for tool activity. That keeps it reading as part of an instrument rather than as
a messaging app bolted into a sci-fi frame.

Entries are rendered from :class:`ConversationEntry` snapshots. The widget holds
no conversation state of its own.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bob.ui.captions import EMPTY_CONVERSATION
from bob.ui.theme.tokens import Theme
from bob.ui.viewmodel import ConversationEntry, EntryKind, Speaker
from bob.ui.widgets.primitives import Label

#: Gutter rule width, in px.
_GUTTER = 2


class EntryView(QWidget):
    """One line in the stream."""

    def __init__(
        self, entry: ConversationEntry, theme: Theme, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._entry = entry

        row = QHBoxLayout(self)
        row.setContentsMargins(0, theme.space.xs, 0, theme.space.xs)
        row.setSpacing(theme.space.md)

        gutter = QWidget()
        gutter.setFixedWidth(_GUTTER)
        gutter.setStyleSheet(
            f"background: {self._gutter_color()}; border-radius: {_GUTTER // 2}px;"
        )
        row.addWidget(gutter)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.space.xxs)

        speaker = Label(self._speaker_label(), theme, "status")
        speaker.set_tone(self._speaker_tone())
        column.addWidget(speaker)

        # A tool entry already names itself in the speaker slot; repeating the
        # name as body text would just be noise.
        if entry.kind is not EntryKind.TOOL:
            body = Label(self._body_text(), theme, self._body_role())
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if entry.kind is EntryKind.ERROR:
                body.set_tone("error")
            elif entry.kind is EntryKind.NOTE:
                body.set_tone("muted")
            column.addWidget(body)

        # Tool results collapse to a single summary line; Phase 9 will make this
        # expandable for structured output.
        if entry.kind is EntryKind.TOOL:
            detail = Label(self._tool_detail(), theme, "data")
            detail.set_tone("muted" if entry.tool_ok is not False else "error")
            detail.setWordWrap(True)
            column.addWidget(detail)

        row.addLayout(column, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    # -- appearance rules ------------------------------------------------

    def _gutter_color(self) -> str:
        p = self._theme.palette
        match self._entry.kind, self._entry.speaker:
            case EntryKind.ERROR, _:
                return p.status.error
            case EntryKind.TOOL, _:
                return p.status.executing
            case EntryKind.NOTE, _:
                return p.line.default
            case _, Speaker.BOB:
                return p.accent
            case _:
                return p.line.strong

    def _speaker_label(self) -> str:
        match self._entry.kind, self._entry.speaker:
            case EntryKind.TOOL, _:
                return self._entry.tool_name or "ΕΝΕΡΓΕΙΑ"
            case EntryKind.ERROR, _:
                return "ΣΦΑΛΜΑ"
            case EntryKind.NOTE, _:
                return "ΣΥΣΤΗΜΑ"
            case _, Speaker.BOB:
                return "B.O.B."
            case _:
                return "ΕΣΥ"

    def _speaker_tone(self) -> str:
        match self._entry.kind, self._entry.speaker:
            case EntryKind.ERROR, _:
                return "error"
            case EntryKind.TOOL, _:
                return "warning"
            case _, Speaker.BOB:
                return "accent"
            case _:
                return "muted"

    def _body_role(self) -> str:
        return "data" if self._entry.kind is EntryKind.TOOL else "body"

    def _body_text(self) -> str:
        text = self._entry.text
        # A caret shows text is still arriving, without animating anything.
        return f"{text}▌" if self._entry.streaming else text

    def _tool_detail(self) -> str:
        entry = self._entry
        if entry.tool_ok is None:
            return "εκτελείται…"
        status = "✓" if entry.tool_ok else "✕"
        parts = [status]
        if entry.tool_detail:
            parts.append(entry.tool_detail)
        if entry.duration_ms:
            parts.append(f"{entry.duration_ms:.0f}ms")
        return "  ".join(parts)


class ConversationView(QScrollArea):
    """Scrolling stream of entries, rebuilt from a snapshot."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._rendered: tuple[ConversationEntry, ...] = ()

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setAccessibleName("Συνομιλία")

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, theme.space.sm, 0)
        self._layout.setSpacing(theme.space.xs)
        self._layout.addStretch(1)
        self.setWidget(self._content)

        self._empty = Label(EMPTY_CONVERSATION, theme, "caption")
        self._empty.set_tone("muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.insertWidget(0, self._empty)

    def set_entries(self, entries: tuple[ConversationEntry, ...]) -> None:
        """Render a snapshot.

        Rebuilds only when the entry list actually differs — the shell hands us
        a new snapshot on every event, most of which change nothing here.
        """
        if entries == self._rendered:
            return
        at_bottom = self._at_bottom()
        self._rendered = entries
        self._clear()

        if not entries:
            self._empty.show()
            self._layout.insertWidget(0, self._empty)
            return

        self._empty.hide()
        for index, entry in enumerate(entries):
            self._layout.insertWidget(index, EntryView(entry, self._theme))

        if at_bottom:
            self._scroll_to_bottom()

    # -- helpers ---------------------------------------------------------

    def _clear(self) -> None:
        while self._layout.count() > 1:  # keep the trailing stretch
            item = self._layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None and widget is not self._empty:
                widget.deleteLater()

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - 8

    def _scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
