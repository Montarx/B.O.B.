"""Design-system guarantees.

These are the tests that stop the interface drifting into an inconsistent pile
of ad-hoc styling, and that keep the accessibility promises real rather than
aspirational.
"""

from __future__ import annotations

import dataclasses

import pytest

from bob.ui.theme.color import (
    contrast_ratio,
    mix,
    over,
    parse_hex,
    rgba,
    to_hex,
)
from bob.ui.theme.stylesheet import build_stylesheet
from bob.ui.theme.tokens import DEFAULT_THEME, Theme

#: WCAG 2.1 AA for normal text.
AA_NORMAL = 4.5
#: WCAG 2.1 AA for large/bold text and meaningful graphics.
AA_LARGE = 3.0


# -- colour maths -----------------------------------------------------------


def test_parse_and_roundtrip_hex() -> None:
    assert parse_hex("#4FD9E8") == (79, 217, 232)
    assert parse_hex("#FFF") == (255, 255, 255)
    assert to_hex((79, 217, 232)) == "#4FD9E8"


def test_invalid_hex_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_hex("not-a-colour")


def test_mix_endpoints_and_midpoint() -> None:
    assert mix("#000000", "#FFFFFF", 0.0) == "#000000"
    assert mix("#000000", "#FFFFFF", 1.0) == "#FFFFFF"
    assert mix("#000000", "#FFFFFF", 0.5) == "#808080"


def test_contrast_ratio_extremes() -> None:
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0, abs=0.01)


def test_rgba_is_qss_compatible() -> None:
    """QSS understands rgba(); it does not understand #RRGGBBAA."""
    assert rgba("#4FD9E8", 0.5) == "rgba(79, 217, 232, 0.500)"


def test_over_composites_translucency() -> None:
    assert over("#FFFFFF", "#000000", 0.5) == "#808080"


# -- accessibility ----------------------------------------------------------


@pytest.mark.parametrize("surface_name", ["base", "raised", "overlay", "sunken"])
def test_body_text_meets_aa_on_every_surface(surface_name: str) -> None:
    p = DEFAULT_THEME.palette
    surface = getattr(p.surface, surface_name)
    assert contrast_ratio(p.ink.primary, surface) >= AA_NORMAL
    assert contrast_ratio(p.ink.secondary, surface) >= AA_NORMAL


@pytest.mark.parametrize("surface_name", ["base", "raised", "overlay", "sunken"])
def test_tertiary_ink_meets_large_text_aa(surface_name: str) -> None:
    """Tertiary is used for small labels, so it still has to clear 3:1."""
    p = DEFAULT_THEME.palette
    surface = getattr(p.surface, surface_name)
    assert contrast_ratio(p.ink.tertiary, surface) >= AA_LARGE


@pytest.mark.parametrize(
    "status",
    ["idle", "listening", "transcribing", "thinking", "executing", "speaking", "error"],
)
def test_status_colours_are_legible_as_text(status: str) -> None:
    """Status hues label things, so they must be readable, not just pretty."""
    p = DEFAULT_THEME.palette
    colour = getattr(p.status, status)
    assert contrast_ratio(colour, p.surface.raised) >= AA_LARGE


def test_offline_colour_is_deliberately_dim() -> None:
    """OFFLINE is the one status never used for text — it signals dormancy."""
    p = DEFAULT_THEME.palette
    assert contrast_ratio(p.status.offline, p.surface.raised) < AA_LARGE


def test_no_type_role_is_microscopic() -> None:
    """A sci-fi look is not an excuse for unreadable text."""
    t = DEFAULT_THEME.type
    roles = [
        t.wordmark,
        t.tagline,
        t.title,
        t.panel_header,
        t.body,
        t.body_strong,
        t.caption,
        t.status,
        t.metric,
        t.data,
    ]
    assert all(role.size >= 9 for role in roles)
    assert t.body.size >= 13


def test_focus_ring_is_clearly_visible() -> None:
    p = DEFAULT_THEME.palette
    assert contrast_ratio(p.focus, p.surface.base) >= AA_LARGE


def test_every_font_family_stack_has_a_generic_fallback() -> None:
    t = DEFAULT_THEME.type
    assert t.ui_families[-1] == "sans-serif"
    assert t.mono_families[-1] == "monospace"


# -- theme behaviour --------------------------------------------------------


def test_accent_override_preserves_everything_else() -> None:
    theme = DEFAULT_THEME.with_accent("#FF00AA")
    assert theme.palette.accent == "#FF00AA"
    assert theme.palette.ink.primary == DEFAULT_THEME.palette.ink.primary
    assert theme.space == DEFAULT_THEME.space


def test_reduced_motion_removes_durations_and_lowers_fps() -> None:
    theme = DEFAULT_THEME.with_reduced_motion(True)
    assert theme.reduced_motion
    assert theme.motion.base == 0
    assert theme.motion.slower == 0
    assert theme.motion.idle_fps == theme.motion.reduced_motion_fps
    assert theme.motion.idle_fps < DEFAULT_THEME.motion.idle_fps


def test_reduced_motion_is_reversible() -> None:
    theme = DEFAULT_THEME.with_reduced_motion(True).with_reduced_motion(False)
    assert not theme.reduced_motion
    assert theme.motion.idle_fps == DEFAULT_THEME.motion.idle_fps


def test_reduced_motion_noop_returns_same_object() -> None:
    assert DEFAULT_THEME.with_reduced_motion(False) is DEFAULT_THEME


def test_spacing_scale_is_monotonic() -> None:
    s = DEFAULT_THEME.space
    steps = [s.xxs, s.xs, s.sm, s.md, s.lg, s.xl, s.xxl, s.huge]
    assert steps == sorted(steps)
    assert len(set(steps)) == len(steps)


def test_spacing_can_be_densified_for_small_screens() -> None:
    dense = DEFAULT_THEME.space.scaled(0.75)
    assert dense.lg < DEFAULT_THEME.space.lg
    assert dense.none == 0


def test_glow_levels_are_ordered() -> None:
    g = DEFAULT_THEME.glow
    radii = [g.level(name)[0] for name in ("none", "soft", "medium", "strong")]
    assert radii == sorted(radii)


def test_unknown_glow_level_raises() -> None:
    with pytest.raises(KeyError):
        DEFAULT_THEME.glow.level("nuclear")


# -- stylesheet -------------------------------------------------------------


def test_stylesheet_is_generated_from_tokens() -> None:
    qss = build_stylesheet(DEFAULT_THEME)
    assert DEFAULT_THEME.palette.accent in qss
    assert DEFAULT_THEME.palette.surface.void in qss
    assert f"{DEFAULT_THEME.radius.lg}px" in qss


def test_stylesheet_tracks_a_custom_accent() -> None:
    qss = build_stylesheet(DEFAULT_THEME.with_accent("#FF00AA"))
    assert "#FF00AA" in qss


def test_stylesheet_covers_every_interactive_state() -> None:
    """Hover, focus, pressed and disabled must all be defined, not left to Qt."""
    qss = build_stylesheet(DEFAULT_THEME)
    for pseudo in (":hover", ":focus", ":pressed", ":disabled"):
        assert pseudo in qss, f"stylesheet defines no {pseudo} state"


def test_stylesheet_has_balanced_braces() -> None:
    qss = build_stylesheet(DEFAULT_THEME)
    assert qss.count("{") == qss.count("}")


def test_stylesheet_uses_no_raw_colour_outside_the_palette() -> None:
    """Every hex literal in the stylesheet must come from the theme."""
    import re

    theme = DEFAULT_THEME
    p = theme.palette
    known = {
        c.upper()
        for c in (
            p.accent,
            p.accent_dim,
            p.accent_bright,
            p.focus,
            p.surface.void,
            p.surface.base,
            p.surface.raised,
            p.surface.overlay,
            p.surface.sunken,
            p.surface.scrim,
            p.ink.primary,
            p.ink.secondary,
            p.ink.tertiary,
            p.ink.disabled,
            p.ink.inverse,
            p.line.subtle,
            p.line.default,
            p.line.strong,
            p.line.accent,
            p.status.error,
            p.status.warning,
            p.status.ok,
        )
    }
    found = {m.upper() for m in re.findall(r"#[0-9A-Fa-f]{6}", build_stylesheet(theme))}
    assert found <= known, f"stylesheet contains off-palette colours: {found - known}"


def test_hit_targets_are_comfortable() -> None:
    """Interactive controls must not be fiddly to click."""
    assert DEFAULT_THEME.icon.hit_target >= 24
    qss = build_stylesheet(DEFAULT_THEME)
    assert f"min-height: {DEFAULT_THEME.icon.hit_target}px" in qss


def test_theme_is_immutable() -> None:
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        DEFAULT_THEME.name = "other"  # type: ignore[misc]


def test_default_theme_is_a_theme() -> None:
    assert isinstance(DEFAULT_THEME, Theme)
    assert DEFAULT_THEME.name == "orbit-dark"
