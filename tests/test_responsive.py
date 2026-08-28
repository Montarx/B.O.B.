"""Responsive layout rules."""

from __future__ import annotations

import pytest

from bob.ui.responsive import (
    Breakpoint,
    breakpoint_for_width,
    core_diameter,
    layout_for_width,
)

#: Real screen widths B.O.B. has to work on.
LAPTOP = 1366
HD = 1920
QHD = 2560
UHD = 3840


@pytest.mark.parametrize(
    ("width", "expected"),
    [
        (1024, Breakpoint.COMPACT),
        (1180, Breakpoint.COMPACT),
        (1181, Breakpoint.MEDIUM),
        (LAPTOP, Breakpoint.MEDIUM),
        (1500, Breakpoint.MEDIUM),
        (1501, Breakpoint.WIDE),
        (HD, Breakpoint.WIDE),
        (QHD, Breakpoint.ULTRA),
        (UHD, Breakpoint.ULTRA),
    ],
)
def test_breakpoint_classification(width: int, expected: Breakpoint) -> None:
    assert breakpoint_for_width(width) == expected


def test_design_target_shows_the_full_three_columns() -> None:
    layout = layout_for_width(HD)
    assert layout.show_left_rail
    assert layout.show_right_rail


def test_laptop_keeps_the_more_useful_rail() -> None:
    """At 1366x768 something must go; the activity rail is the one to drop."""
    layout = layout_for_width(LAPTOP)
    assert not layout.show_left_rail
    assert layout.show_right_rail


def test_compact_drops_both_rails_but_never_the_core() -> None:
    layout = layout_for_width(1024)
    assert not layout.show_left_rail
    assert not layout.show_right_rail
    assert layout.center_max_width > 0


def test_rails_degrade_in_order_as_width_shrinks() -> None:
    """Rails must disappear one at a time, never both at once."""
    visible = [
        sum(
            (
                layout_for_width(w).show_left_rail,
                layout_for_width(w).show_right_rail,
            )
        )
        for w in (1000, LAPTOP, HD, UHD)
    ]
    assert visible == sorted(visible)


def test_hidden_rails_take_no_width() -> None:
    layout = layout_for_width(1024)
    assert layout.left_rail_width == 0
    assert layout.right_rail_width == 0


def test_centre_column_is_capped_on_huge_screens() -> None:
    """On 4K the core should not stretch into an enormous orb."""
    assert layout_for_width(UHD).center_max_width < UHD // 2


def test_centre_cap_grows_monotonically_with_width() -> None:
    caps = [layout_for_width(w).center_max_width for w in (1024, LAPTOP, HD, QHD)]
    assert caps == sorted(caps)


def test_core_diameter_is_clamped_at_both_ends() -> None:
    tiny = core_diameter(120, layout_for_width(1024))
    huge = core_diameter(4000, layout_for_width(UHD))
    assert tiny >= 200  # below this the layered detail stops reading
    assert huge <= 460  # above this it dominates a 4K screen


def test_core_diameter_scales_with_available_space() -> None:
    layout = layout_for_width(HD)
    assert core_diameter(400, layout) < core_diameter(600, layout)


def test_compact_layout_renders_a_simpler_core() -> None:
    assert layout_for_width(1024).compact_core
    assert not layout_for_width(HD).compact_core


def test_small_screens_get_tighter_spacing() -> None:
    assert layout_for_width(1024).density < layout_for_width(HD).density


def test_layouts_are_comparable_values() -> None:
    """The window skips relayout work when the spec has not changed."""
    assert layout_for_width(HD) == layout_for_width(HD + 1)
