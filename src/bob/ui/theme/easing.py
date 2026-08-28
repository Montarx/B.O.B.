"""Mapping motion tokens to Qt easing curves."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve

_CURVES = {
    "Linear": QEasingCurve.Type.Linear,
    "OutCubic": QEasingCurve.Type.OutCubic,
    "InCubic": QEasingCurve.Type.InCubic,
    "InOutCubic": QEasingCurve.Type.InOutCubic,
    "OutQuint": QEasingCurve.Type.OutQuint,
    "OutBack": QEasingCurve.Type.OutBack,
}


def curve(name: str) -> QEasingCurve:
    """Resolve an easing token name; unknown names fall back to linear."""
    return QEasingCurve(_CURVES.get(name, QEasingCurve.Type.Linear))


def ease(name: str, t: float) -> float:
    """Evaluate an easing curve at ``t`` in 0..1. Used by the core animation."""
    return float(curve(name).valueForProgress(max(0.0, min(1.0, t))))
