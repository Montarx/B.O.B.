"""Colour maths on hex strings.

Pure functions, no Qt. Two consumers:

* the stylesheet builder, which needs alpha compositing and tints;
* the core animation, which interpolates between state colours every frame.

:func:`contrast_ratio` exists so accessibility is checked by the test suite
rather than assumed.
"""

from __future__ import annotations

RGB = tuple[int, int, int]
#: Intermediate results of blending are fractional before being rounded back.
RGBLike = tuple[float, float, float]


def parse_hex(value: str) -> RGB:
    """Parse ``#RRGGBB`` (or ``#RGB``) into an RGB triple."""
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"not a hex colour: {value!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def to_hex(rgb: RGB | RGBLike) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def rgba(value: str, alpha: float) -> str:
    """CSS/QSS ``rgba(...)`` string — QSS understands this, ``#RRGGBBAA`` it does not."""
    r, g, b = parse_hex(value)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, alpha)):.3f})"


def mix(a: str, b: str, t: float) -> str:
    """Linear blend of two colours; ``t=0`` gives ``a``, ``t=1`` gives ``b``."""
    t = max(0.0, min(1.0, t))
    ar, ag, ab = parse_hex(a)
    br, bg, bb = parse_hex(b)
    return to_hex((ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t))


def over(foreground: str, background: str, alpha: float) -> str:
    """Composite ``foreground`` at ``alpha`` over an opaque ``background``.

    Used to compute the *effective* colour of a translucent surface so its
    contrast can be measured honestly.
    """
    return mix(background, foreground, alpha)


def lighten(value: str, amount: float) -> str:
    return mix(value, "#FFFFFF", amount)


def darken(value: str, amount: float) -> str:
    return mix(value, "#000000", amount)


def _channel_luminance(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(value: str) -> float:
    """WCAG 2.1 relative luminance."""
    r, g, b = parse_hex(value)
    return (
        0.2126 * _channel_luminance(r)
        + 0.7152 * _channel_luminance(g)
        + 0.0722 * _channel_luminance(b)
    )


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.1 contrast ratio between two opaque colours (1.0 .. 21.0)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)
