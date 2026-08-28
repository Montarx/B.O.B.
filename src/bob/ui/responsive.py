"""Responsive layout rules.

Pure functions over a window width, so breakpoint behaviour is unit-tested
rather than discovered by dragging a window. The shell asks
:func:`layout_for_width` on every resize and applies the answer; no widget
computes its own geometry from screen size.

Design target is 1920x1080. The breakpoints below are chosen so the two side
rails degrade in a sensible order rather than all at once: the system panel is
useful-but-optional, the activity rail is more useful, and the core plus the
conversation are never sacrificed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Breakpoint(StrEnum):
    COMPACT = "compact"  # <= 1180 : one column, core + conversation only
    MEDIUM = "medium"  # <= 1500 : core + conversation + activity rail
    WIDE = "wide"  # <= 2200 : the full three-column design target
    ULTRA = "ultra"  # >  2200 : wider rails, capped centre column


#: Upper bound (inclusive) of each breakpoint, in logical pixels.
BREAKPOINT_BOUNDS: tuple[tuple[int, Breakpoint], ...] = (
    (1180, Breakpoint.COMPACT),
    (1500, Breakpoint.MEDIUM),
    (2200, Breakpoint.WIDE),
)


@dataclass(frozen=True, slots=True)
class ShellLayout:
    """What the shell should show at a given width."""

    breakpoint: Breakpoint
    show_left_rail: bool
    show_right_rail: bool
    left_rail_width: int
    right_rail_width: int
    #: Maximum width of the centre column; beyond this the core stops growing
    #: and the layout gains margins instead of a stretched orb.
    center_max_width: int
    #: Multiplier applied to the spacing scale, for tighter small screens.
    density: float
    #: Whether the core should render at reduced fidelity (fewer nodes).
    compact_core: bool


def breakpoint_for_width(width: int) -> Breakpoint:
    """Classify a window width."""
    for bound, name in BREAKPOINT_BOUNDS:
        if width <= bound:
            return name
    return Breakpoint.ULTRA


def layout_for_width(width: int) -> ShellLayout:
    """Resolve the full layout for a window width."""
    bp = breakpoint_for_width(width)
    match bp:
        case Breakpoint.COMPACT:
            return ShellLayout(
                breakpoint=bp,
                show_left_rail=False,
                show_right_rail=False,
                left_rail_width=0,
                right_rail_width=0,
                center_max_width=880,
                density=0.75,
                compact_core=True,
            )
        case Breakpoint.MEDIUM:
            return ShellLayout(
                breakpoint=bp,
                show_left_rail=False,
                show_right_rail=True,
                left_rail_width=0,
                right_rail_width=288,
                center_max_width=1000,
                density=0.9,
                compact_core=False,
            )
        case Breakpoint.WIDE:
            return ShellLayout(
                breakpoint=bp,
                show_left_rail=True,
                show_right_rail=True,
                left_rail_width=280,
                right_rail_width=300,
                center_max_width=1120,
                density=1.0,
                compact_core=False,
            )
        case _:
            return ShellLayout(
                breakpoint=Breakpoint.ULTRA,
                show_left_rail=True,
                show_right_rail=True,
                left_rail_width=340,
                right_rail_width=360,
                center_max_width=1280,
                density=1.0,
                compact_core=False,
            )


def core_diameter(available: int, layout: ShellLayout) -> int:
    """Pick the core's drawing diameter for the space it has been given.

    Clamped at both ends: below ~200px the layered detail stops being legible,
    and above ~460px the core starts to dominate a 4K screen unpleasantly.
    """
    target = int(available * (0.62 if layout.compact_core else 0.68))
    return max(200, min(460, target))
