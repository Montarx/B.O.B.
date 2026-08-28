"""The content panels: activity, current task, system, providers.

All four are thin renderers over the view model. None of them holds state, does
I/O, or knows the kernel exists.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from bob.ui.captions import EMPTY_ACTIVITY, NO_TASK
from bob.ui.theme.tokens import Theme
from bob.ui.viewmodel import (
    ActionRecord,
    ProviderInfo,
    SystemStats,
    TaskInfo,
)
from bob.ui.widgets.primitives import Label, Meter, Panel, StatusDot


class MetricRow(QWidget):
    """Label, value and a slim meter — the one way B.O.B. shows a number."""

    def __init__(
        self,
        name: str,
        theme: Theme,
        *,
        show_meter: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.space.xs)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.space.sm)
        self._name = Label(name, theme, "caption")
        self._name.set_tone("muted")
        self._value = Label("—", theme, "data")
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._name)
        row.addStretch(1)
        row.addWidget(self._value)
        column.addLayout(row)

        self._meter = Meter(theme) if show_meter else None
        if self._meter is not None:
            column.addWidget(self._meter)

    def set(self, value_text: str, fraction: float | None = None) -> None:
        self._value.setText(value_text)
        if self._meter is not None and fraction is not None:
            self._meter.set_value(fraction)
            self._meter.set_color(self._color_for(fraction))

    def _color_for(self, fraction: float) -> str:
        status = self._theme.palette.status
        if fraction >= 0.9:
            return status.error
        if fraction >= 0.75:
            return status.warning
        return self._theme.palette.accent


class SystemPanel(Panel):
    """CPU / RAM / disk / network. Mock values in Phase 1."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, "ΣΥΣΤΗΜΑ", parent=parent)
        self._cpu = MetricRow("CPU", theme)
        self._ram = MetricRow("RAM", theme)
        self._disk = MetricRow("Δίσκος", theme)
        self._net = MetricRow("Δίκτυο", theme, show_meter=False)
        for row in (self._cpu, self._ram, self._disk, self._net):
            self.body.addWidget(row)

    def set_stats(self, stats: SystemStats) -> None:
        self._cpu.set(f"{stats.cpu_percent:.0f}%", stats.cpu_percent / 100.0)
        self._ram.set(
            f"{stats.ram_used_gb:.1f} / {stats.ram_total_gb:.0f} GB",
            stats.ram_percent / 100.0,
        )
        self._disk.set(f"{stats.disk_percent:.0f}%", stats.disk_percent / 100.0)
        self._net.set(f"{stats.network_kbps:.0f} KB/s")


class ProviderPanel(Panel):
    """What B.O.B. is running on. Honest about being simulated."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, "ΜΟΝΤΕΛΑ", parent=parent)
        self._theme = theme
        self._rows = {
            key: MetricRow(label, theme, show_meter=False)
            for key, label in (
                ("llm", "Σκέψη"),
                ("stt", "Ακοή"),
                ("tts", "Φωνή"),
                ("wakeword", "Wake word"),
            )
        }
        for row in self._rows.values():
            self.body.addWidget(row)

        self._notice = Label("", theme, "caption")
        self._notice.set_tone("warning")
        self._notice.setWordWrap(True)
        self.body.addWidget(self._notice)

    def set_providers(self, providers: ProviderInfo) -> None:
        self._rows["llm"].set(providers.llm)
        self._rows["stt"].set(providers.stt)
        self._rows["tts"].set(providers.tts)
        self._rows["wakeword"].set(providers.wakeword)
        self._notice.setText(
            "Προσομοίωση — δεν τρέχει πραγματικό μοντέλο ακόμα." if providers.simulated else ""
        )
        self._notice.setVisible(providers.simulated)


class TaskPanel(Panel):
    """The action B.O.B. is performing right now."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, "ΤΡΕΧΟΥΣΑ ΕΝΕΡΓΕΙΑ", parent=parent)
        self._theme = theme
        self._dot = StatusDot(theme, size=8)
        self.add_header_widget(self._dot)

        self._title = Label(NO_TASK, theme, "bodyStrong")
        self._title.setWordWrap(True)
        self._detail = Label("", theme, "caption")
        self._detail.set_tone("muted")
        self._detail.setWordWrap(True)
        self._meter = Meter(theme)

        self.body.addWidget(self._title)
        self.body.addWidget(self._detail)
        self.body.addWidget(self._meter)

    def set_task(self, task: TaskInfo) -> None:
        status = self._theme.palette.status
        if not task.active:
            self._title.setText(NO_TASK)
            self._title.set_tone("muted")
            self._detail.setText("")
            self._detail.hide()
            self._meter.hide()
            self._dot.set_color(status.offline)
            self._dot.set_pulse(False)
            return

        self._title.setText(task.title)
        self._title.set_tone("")
        self._detail.setText(task.detail)
        self._detail.setVisible(bool(task.detail))
        self._dot.set_color(status.executing)
        self._dot.set_pulse(True)

        # Indeterminate work shows a half-filled bar rather than a fake percentage.
        self._meter.show()
        self._meter.set_color(status.executing)
        self._meter.set_value(0.5 if task.progress is None else task.progress)


class ActivityPanel(Panel):
    """Recent actions, newest first."""

    MAX_ROWS = 8

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(theme, "ΠΡΟΣΦΑΤΑ", parent=parent)
        self._theme = theme
        self._rendered: tuple[ActionRecord, ...] = ()
        self._rows: list[QWidget] = []

        self._empty = Label(EMPTY_ACTIVITY, theme, "caption")
        self._empty.set_tone("muted")
        self.body.addWidget(self._empty)
        self.body.addStretch(1)

    def set_actions(self, actions: tuple[ActionRecord, ...]) -> None:
        if actions == self._rendered:
            return
        self._rendered = actions

        for row in self._rows:
            self.body.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        self._empty.setVisible(not actions)
        for index, record in enumerate(actions[: self.MAX_ROWS]):
            row = self._build_row(record)
            self.body.insertWidget(index, row)
            self._rows.append(row)

    def _build_row(self, record: ActionRecord) -> QWidget:
        theme = self._theme
        widget = QWidget()
        widget.setProperty("role", "row")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(theme.space.xs, theme.space.xxs, theme.space.xs, theme.space.xxs)
        layout.setSpacing(theme.space.sm)

        dot = StatusDot(theme, size=6)
        dot.set_color(theme.palette.status.ok if record.ok else theme.palette.status.error)
        layout.addWidget(dot)

        name = Label(record.tool, theme, "data")
        layout.addWidget(name)
        layout.addStretch(1)

        duration = Label(f"{record.duration_ms:.0f}ms", theme, "data")
        duration.set_tone("muted")
        layout.addWidget(duration)
        return widget
