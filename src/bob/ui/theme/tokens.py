"""Design tokens — the single source of truth for how B.O.B. looks.

Deliberately free of Qt imports. Tokens are plain data, so the whole design
system (including contrast ratios) is testable without a display server, and so
no widget is ever tempted to invent its own colour or spacing.

**Visual identity: "Orrery".**
B.O.B. is Beyond Orbit Buddy, so the reference is an armillary sphere — an
antique astronomical instrument — rendered matte and modern. Light comes from
edges, not from bloom. Surfaces are deep and quiet. Strokes are thin. The
palette is cool with a single warm accent reserved for action.

Rules for anyone adding to this file:

* No widget defines a colour, radius, duration or font size of its own.
* Every colour that carries text must pass the contrast test in the test suite.
* Motion durations come from :class:`Motion`, never from a literal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# ---------------------------------------------------------------------------
# Colour primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Surfaces:
    """Background layers, darkest to lightest. Depth comes from value, not shadow."""

    void: str = "#05070D"  # the window ground; deep field, not pure black
    base: str = "#080B14"  # default panel body
    raised: str = "#0D121D"  # panels that sit above the base
    overlay: str = "#131A29"  # popovers, debug overlay, hovered rows
    sunken: str = "#04060B"  # wells: the core stage, input field interior
    scrim: str = "#03050A"  # modal dimming


@dataclass(frozen=True, slots=True)
class Ink:
    """Foreground text, most to least prominent."""

    primary: str = "#E9EEF8"  # body copy and headings
    secondary: str = "#A6B2C7"  # supporting copy, still fully readable
    tertiary: str = "#7A879E"  # de-emphasised labels; never below 3:1
    disabled: str = "#4C566B"  # non-interactive only, never load-bearing
    inverse: str = "#05070D"  # text on an accent fill


@dataclass(frozen=True, slots=True)
class Lines:
    """Borders and dividers. Thin and low-contrast; structure, not decoration."""

    subtle: str = "#161D2C"
    default: str = "#1E2839"
    strong: str = "#2B384E"
    accent: str = "#245C69"


@dataclass(frozen=True, slots=True)
class StatusColors:
    """One hue per meaning. These drive both the UI and the core animation."""

    idle: str = "#4FD9E8"  # aqua — B.O.B.'s resting signature
    wake: str = "#8BF4FF"  # brighter aqua, the flash of attention
    listening: str = "#5EE9C7"  # mint — receptive
    transcribing: str = "#7FB2F0"  # blue — mechanical, controlled
    thinking: str = "#A78BFA"  # violet — abstract work
    executing: str = "#F2B57A"  # amber — the only warm hue, reserved for action
    speaking: str = "#4FD9E8"  # aqua, matching idle: B.O.B.'s own voice
    error: str = "#FF8080"  # coral, not fire-engine red
    offline: str = "#39435A"  # slate — dormant, clearly inert
    ok: str = "#5EE9C7"
    warning: str = "#F2B57A"


@dataclass(frozen=True, slots=True)
class Palette:
    surface: Surfaces = field(default_factory=Surfaces)
    ink: Ink = field(default_factory=Ink)
    line: Lines = field(default_factory=Lines)
    status: StatusColors = field(default_factory=StatusColors)

    accent: str = "#4FD9E8"
    accent_dim: str = "#2A7C89"
    accent_bright: str = "#8BF4FF"
    focus: str = "#8BF4FF"  # keyboard focus ring — deliberately loud


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FontRole:
    """One typographic role. ``tracking`` is in 1/100 em, as Qt expects."""

    size: int
    weight: int = 400
    tracking: float = 0.0
    uppercase: bool = False
    mono: bool = False
    line_height: float = 1.45


#: Families are ordered fallbacks. Greek coverage is required of every entry,
#: which rules out several popular UI fonts.
UI_FAMILIES: Final[tuple[str, ...]] = (
    "Inter",
    "Segoe UI Variable Text",
    "Segoe UI",
    "Noto Sans",
    "DejaVu Sans",
    "sans-serif",
)

MONO_FAMILIES: Final[tuple[str, ...]] = (
    "JetBrains Mono",
    "Cascadia Mono",
    "Consolas",
    "DejaVu Sans Mono",
    "monospace",
)


@dataclass(frozen=True, slots=True)
class Typography:
    """The type scale.

    Nothing here is smaller than 10px, and body copy is 13px — a sci-fi look is
    not an excuse for text the user has to lean in to read.
    """

    # Brand
    wordmark: FontRole = FontRole(size=20, weight=700, tracking=6.0, uppercase=True)
    tagline: FontRole = FontRole(size=9, weight=500, tracking=3.4, uppercase=True)

    # Structure
    title: FontRole = FontRole(size=15, weight=600, tracking=0.2)
    panel_header: FontRole = FontRole(size=10, weight=600, tracking=1.8, uppercase=True)

    # Content
    body: FontRole = FontRole(size=13, weight=400)
    body_strong: FontRole = FontRole(size=13, weight=600)
    caption: FontRole = FontRole(size=11, weight=400, line_height=1.4)

    # Signals and data
    status: FontRole = FontRole(size=11, weight=600, tracking=1.6, uppercase=True)
    metric: FontRole = FontRole(size=15, weight=500, mono=True)
    data: FontRole = FontRole(size=11, weight=400, mono=True)

    ui_families: tuple[str, ...] = UI_FAMILIES
    mono_families: tuple[str, ...] = MONO_FAMILIES

    def family(self, role: FontRole) -> str:
        families = self.mono_families if role.mono else self.ui_families
        return ", ".join(f'"{f}"' if " " in f else f for f in families)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Spacing:
    """A 4px rhythm. Layout code uses these names, never raw pixels."""

    none: int = 0
    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    huge: int = 48

    def scaled(self, factor: float) -> Spacing:
        """Density variant for small screens (see :mod:`bob.ui.responsive`)."""

        def r(value: int) -> int:
            return max(0, round(value * factor))

        return Spacing(
            none=0,
            xxs=r(self.xxs),
            xs=r(self.xs),
            sm=r(self.sm),
            md=r(self.md),
            lg=r(self.lg),
            xl=r(self.xl),
            xxl=r(self.xxl),
            huge=r(self.huge),
        )


@dataclass(frozen=True, slots=True)
class Radii:
    """Restrained curvature. Nothing is a pill except deliberate badges."""

    none: int = 0
    sm: int = 3
    md: int = 6
    lg: int = 10
    xl: int = 14
    pill: int = 999


@dataclass(frozen=True, slots=True)
class Borders:
    hairline: int = 1
    thick: int = 2
    focus_ring: int = 2


@dataclass(frozen=True, slots=True)
class IconSizes:
    xs: int = 12
    sm: int = 14
    md: int = 16
    lg: int = 20
    xl: int = 24

    #: Minimum comfortable click target, in px. Enforced on interactive widgets.
    hit_target: int = 28


# ---------------------------------------------------------------------------
# Light and depth
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Glow:
    """Glow is a budget, not a decoration.

    Four levels only. ``alpha`` is 0..1 and is applied to the *status* colour of
    whatever is glowing, so glow always agrees with meaning.
    """

    none_radius: int = 0
    none_alpha: float = 0.0

    soft_radius: int = 12
    soft_alpha: float = 0.18

    medium_radius: int = 22
    medium_alpha: float = 0.30

    strong_radius: int = 36
    strong_alpha: float = 0.46

    def level(self, name: str) -> tuple[int, float]:
        table = {
            "none": (self.none_radius, self.none_alpha),
            "soft": (self.soft_radius, self.soft_alpha),
            "medium": (self.medium_radius, self.medium_alpha),
            "strong": (self.strong_radius, self.strong_alpha),
        }
        return table[name]


@dataclass(frozen=True, slots=True)
class Opacity:
    """Transparency steps. Panels are near-opaque; only the core stage is glassy."""

    full: float = 1.0
    strong: float = 0.86
    medium: float = 0.64
    soft: float = 0.40
    faint: float = 0.20
    ghost: float = 0.08
    disabled: float = 0.38


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Motion:
    """Durations in ms and named easing curves.

    ``ambient_*`` values are animation periods, not transition durations: they
    describe how slowly the core breathes when nothing is happening.
    """

    instant: int = 0
    fast: int = 120  # hover, focus, small colour shifts
    base: int = 200  # default control transition
    slow: int = 320  # panel content changes
    slower: int = 560  # state-to-state visual morph of the core
    ambient_breath_ms: int = 5200
    ambient_orbit_ms: int = 42_000

    ease_standard: str = "OutCubic"  # most transitions
    ease_enter: str = "OutQuint"  # things arriving
    ease_exit: str = "InCubic"  # things leaving
    ease_emphasis: str = "InOutCubic"  # state morphs
    ease_snap: str = "OutBack"  # wake-word activation only
    ease_linear: str = "Linear"  # continuous rotation

    #: Frame budget guards. See :class:`bob.ui.widgets.core_view.CoreView`.
    idle_fps: int = 60
    dormant_fps: int = 8
    reduced_motion_fps: int = 10

    def with_reduced_motion(self) -> Motion:
        """Honour the accessibility setting: near-instant, no ambient drift."""
        return Motion(
            instant=0,
            fast=0,
            base=0,
            slow=0,
            slower=0,
            ambient_breath_ms=0,
            ambient_orbit_ms=0,
            ease_standard="Linear",
            ease_enter="Linear",
            ease_exit="Linear",
            ease_emphasis="Linear",
            ease_snap="Linear",
            ease_linear="Linear",
            idle_fps=self.reduced_motion_fps,
            dormant_fps=self.dormant_fps,
            reduced_motion_fps=self.reduced_motion_fps,
        )


# ---------------------------------------------------------------------------
# The theme
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Theme:
    """Everything a widget is allowed to know about appearance."""

    name: str = "orbit-dark"
    palette: Palette = field(default_factory=Palette)
    type: Typography = field(default_factory=Typography)
    space: Spacing = field(default_factory=Spacing)
    radius: Radii = field(default_factory=Radii)
    border: Borders = field(default_factory=Borders)
    glow: Glow = field(default_factory=Glow)
    opacity: Opacity = field(default_factory=Opacity)
    motion: Motion = field(default_factory=Motion)
    icon: IconSizes = field(default_factory=IconSizes)

    reduced_motion: bool = False

    def with_accent(self, accent: str) -> Theme:
        """Return a copy using a user-chosen accent (``ui.accent`` in config)."""
        palette = Palette(
            surface=self.palette.surface,
            ink=self.palette.ink,
            line=self.palette.line,
            status=self.palette.status,
            accent=accent,
            accent_dim=self.palette.accent_dim,
            accent_bright=self.palette.accent_bright,
            focus=self.palette.focus,
        )
        return self._replace(palette=palette)

    def with_reduced_motion(self, enabled: bool) -> Theme:
        if enabled == self.reduced_motion:
            return self
        motion = self.motion.with_reduced_motion() if enabled else Motion()
        return self._replace(motion=motion, reduced_motion=enabled)

    def _replace(self, **changes: object) -> Theme:
        current = {
            "name": self.name,
            "palette": self.palette,
            "type": self.type,
            "space": self.space,
            "radius": self.radius,
            "border": self.border,
            "glow": self.glow,
            "opacity": self.opacity,
            "motion": self.motion,
            "icon": self.icon,
            "reduced_motion": self.reduced_motion,
        }
        current.update(changes)
        return Theme(**current)  # type: ignore[arg-type]


#: The default theme. Widgets receive a Theme; they never import this directly.
DEFAULT_THEME: Final[Theme] = Theme()
