"""Builds the application stylesheet from tokens.

Pure string construction — no Qt import — so the output can be inspected in
tests. Widgets are selected by **dynamic property**, e.g. ``[role="panel"]``,
rather than by class name: property selectors are stable across Qt versions and
survive Python subclassing, and they let one widget class carry several
appearances.

Two things QSS cannot express are handled elsewhere:

* letter-spacing → :mod:`bob.ui.theme.fonts` (``QFont.setLetterSpacing``)
* glow → ``QGraphicsDropShadowEffect``, applied from :mod:`bob.ui.theme.effects`
"""

from __future__ import annotations

from bob.ui.theme.color import rgba
from bob.ui.theme.tokens import FontRole, Theme


def _font_rule(theme: Theme, role: FontRole) -> str:
    """The QSS-expressible part of a typographic role."""
    parts = [
        f"font-family: {theme.type.family(role)};",
        f"font-size: {role.size}px;",
        f"font-weight: {role.weight};",
    ]
    return " ".join(parts)


def build_stylesheet(theme: Theme) -> str:
    """Render the full application stylesheet."""
    return "\n".join(
        [
            _globals(theme),
            _scrollbars(theme),
            _panels(theme),
            _text(theme),
            _inputs(theme),
            _buttons(theme),
            _misc(theme),
        ]
    ).strip()


def _globals(theme: Theme) -> str:
    p, t = theme.palette, theme.type
    return f"""
/* ---------- global ---------- */
QWidget {{
    {_font_rule(theme, t.body)}
    color: {p.ink.primary};
    background: transparent;
}}
QWidget[role="root"] {{
    background: {p.surface.void};
}}
QWidget:disabled {{
    color: {p.ink.disabled};
}}
QToolTip {{
    background: {p.surface.overlay};
    color: {p.ink.primary};
    border: {theme.border.hairline}px solid {p.line.default};
    border-radius: {theme.radius.sm}px;
    padding: {theme.space.xs}px {theme.space.sm}px;
}}
"""


def _scrollbars(theme: Theme) -> str:
    """Thin, quiet scrollbars. The default Qt ones would break the aesthetic."""
    p, s = theme.palette, theme.space
    return f"""
/* ---------- scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: {s.sm}px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.line.strong};
    border-radius: {theme.radius.sm}px;
    min-height: {s.xxl}px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.accent_dim};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: {s.sm}px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p.line.strong};
    border-radius: {theme.radius.sm}px;
    min-width: {s.xxl}px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0; border: none; background: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
QAbstractScrollArea {{
    background: transparent;
    border: none;
}}
"""


def _panels(theme: Theme) -> str:
    p, s, r = theme.palette, theme.space, theme.radius
    return f"""
/* ---------- panels ---------- */
QFrame[role="panel"] {{
    background: {p.surface.raised};
    border: {theme.border.hairline}px solid {p.line.subtle};
    border-radius: {r.lg}px;
}}
QFrame[role="panel"][emphasis="true"] {{
    border-color: {p.line.accent};
}}
QFrame[role="panel"][flat="true"] {{
    background: {p.surface.base};
}}
QFrame[role="stage"] {{
    background: {p.surface.sunken};
    border: {theme.border.hairline}px solid {p.line.subtle};
    border-radius: {r.xl}px;
}}
QFrame[role="divider"] {{
    background: {p.line.subtle};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QFrame[role="divider"][vertical="true"] {{
    max-width: 1px;
    min-width: 1px;
    max-height: 16777215px;
}}
QWidget[role="titlebar"] {{
    background: {p.surface.base};
    border-bottom: {theme.border.hairline}px solid {p.line.subtle};
}}
QWidget[role="row"] {{
    border-radius: {r.md}px;
    padding: {s.xs}px;
}}
QWidget[role="row"]:hover {{
    background: {rgba(p.surface.overlay, 0.8)};
}}
"""


def _text(theme: Theme) -> str:
    p, t = theme.palette, theme.type
    return f"""
/* ---------- text roles ---------- */
QLabel[type="wordmark"]     {{ {_font_rule(theme, t.wordmark)} color: {p.ink.primary}; }}
QLabel[type="tagline"]      {{ {_font_rule(theme, t.tagline)} color: {p.ink.tertiary}; }}
QLabel[type="title"]        {{ {_font_rule(theme, t.title)} color: {p.ink.primary}; }}
QLabel[type="panelHeader"]  {{ {_font_rule(theme, t.panel_header)} color: {p.ink.tertiary}; }}
QLabel[type="body"]         {{ {_font_rule(theme, t.body)} color: {p.ink.primary}; }}
QLabel[type="bodyStrong"]   {{ {_font_rule(theme, t.body_strong)} color: {p.ink.primary}; }}
QLabel[type="caption"]      {{ {_font_rule(theme, t.caption)} color: {p.ink.secondary}; }}
QLabel[type="status"]       {{ {_font_rule(theme, t.status)} color: {p.ink.secondary}; }}
QLabel[type="metric"]       {{ {_font_rule(theme, t.metric)} color: {p.ink.primary}; }}
QLabel[type="data"]         {{ {_font_rule(theme, t.data)} color: {p.ink.secondary}; }}
QLabel[tone="muted"]        {{ color: {p.ink.tertiary}; }}
QLabel[tone="accent"]       {{ color: {p.accent}; }}
QLabel[tone="warning"]      {{ color: {p.status.warning}; }}
QLabel[tone="error"]        {{ color: {p.status.error}; }}
QLabel:disabled             {{ color: {p.ink.disabled}; }}
"""


def _inputs(theme: Theme) -> str:
    p, s, r = theme.palette, theme.space, theme.radius
    return f"""
/* ---------- inputs ---------- */
QLineEdit {{
    background: {p.surface.sunken};
    border: {theme.border.hairline}px solid {p.line.default};
    border-radius: {r.lg}px;
    padding: {s.sm}px {s.md}px;
    color: {p.ink.primary};
    selection-background-color: {p.accent_dim};
    selection-color: {p.ink.primary};
    min-height: {theme.icon.hit_target}px;
}}
QLineEdit:hover {{
    border-color: {p.line.strong};
}}
QLineEdit:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled {{
    background: {p.surface.base};
    border-color: {p.line.subtle};
    color: {p.ink.disabled};
}}
QLineEdit::placeholder {{
    color: {p.ink.tertiary};
}}
"""


def _buttons(theme: Theme) -> str:
    p, s, r = theme.palette, theme.space, theme.radius
    return f"""
/* ---------- buttons ---------- */
QPushButton {{
    background: {p.surface.overlay};
    border: {theme.border.hairline}px solid {p.line.default};
    border-radius: {r.md}px;
    padding: {s.xs}px {s.md}px;
    color: {p.ink.secondary};
    min-height: {theme.icon.hit_target}px;
}}
QPushButton:hover {{
    background: {p.surface.raised};
    border-color: {p.line.strong};
    color: {p.ink.primary};
}}
QPushButton:pressed {{
    background: {p.surface.base};
}}
QPushButton:focus {{
    border-color: {p.focus};
}}
QPushButton:disabled {{
    background: {p.surface.base};
    border-color: {p.line.subtle};
    color: {p.ink.disabled};
}}
QPushButton[variant="primary"] {{
    background: {p.accent_dim};
    border-color: {p.accent};
    color: {p.ink.primary};
}}
QPushButton[variant="primary"]:hover {{
    background: {p.accent};
    color: {p.ink.inverse};
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    border-color: transparent;
}}
QPushButton[variant="ghost"]:hover {{
    background: {rgba(p.surface.overlay, 0.9)};
    border-color: {p.line.subtle};
}}
QPushButton[variant="danger"] {{
    border-color: {p.status.error};
    color: {p.status.error};
}}
QPushButton[variant="danger"]:hover {{
    background: {rgba(p.status.error, 0.14)};
}}
QPushButton[selected="true"] {{
    border-color: {p.accent};
    color: {p.accent};
    background: {rgba(p.accent, 0.10)};
}}
"""


def _misc(theme: Theme) -> str:
    p, r = theme.palette, theme.radius
    return f"""
/* ---------- misc ---------- */
QWidget[role="debugOverlay"] {{
    background: {rgba(p.surface.overlay, 0.97)};
    border: {theme.border.hairline}px solid {p.line.accent};
    border-radius: {r.lg}px;
}}
QWidget[role="chip"] {{
    background: {rgba(p.surface.overlay, 0.85)};
    border: {theme.border.hairline}px solid {p.line.default};
    border-radius: {r.pill}px;
}}
"""
