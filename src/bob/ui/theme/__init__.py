"""B.O.B.'s design system.

``tokens``, ``color`` and ``stylesheet`` are pure Python and testable without a
display. ``fonts``, ``easing`` and ``effects`` touch Qt.
"""

from bob.ui.theme.stylesheet import build_stylesheet
from bob.ui.theme.tokens import DEFAULT_THEME, FontRole, Theme

__all__ = ["DEFAULT_THEME", "FontRole", "Theme", "build_stylesheet"]
