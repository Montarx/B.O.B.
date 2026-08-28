"""Turning a :class:`FontRole` into a real ``QFont``.

Letter-spacing and small-caps cannot be expressed in Qt Style Sheets, so the
typographic roles are applied here in code. Widgets call :func:`apply_font`
rather than constructing fonts themselves.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

from bob.ui.theme.tokens import FontRole, Theme

_WEIGHTS = {
    300: QFont.Weight.Light,
    400: QFont.Weight.Normal,
    500: QFont.Weight.Medium,
    600: QFont.Weight.DemiBold,
    700: QFont.Weight.Bold,
}


def build_font(theme: Theme, role: FontRole) -> QFont:
    families = list(theme.type.mono_families if role.mono else theme.type.ui_families)
    font = QFont()
    font.setFamilies(families)
    font.setPixelSize(role.size)
    font.setWeight(_WEIGHTS.get(role.weight, QFont.Weight.Normal))
    if role.tracking:
        # PercentageSpacing is relative to the font's natural advance; the token
        # is in 1/100 em, so 6.0 -> 106%.
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.0 + role.tracking)
    font.setCapitalization(
        QFont.Capitalization.AllUppercase if role.uppercase else QFont.Capitalization.MixedCase
    )
    return font


def apply_font(widget: QWidget, theme: Theme, role: FontRole, *, type_name: str = "") -> None:
    """Apply a typographic role to ``widget``.

    ``type_name`` also sets the ``type`` dynamic property so the stylesheet can
    colour the widget consistently.
    """
    widget.setFont(build_font(theme, role))
    if type_name:
        widget.setProperty("type", type_name)
