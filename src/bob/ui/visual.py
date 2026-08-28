"""State to visual behaviour — the rules the animated core obeys.

This module is pure data and pure functions. It contains no Qt and no drawing
code, which means the *meaning* of every animation is unit-testable, separately
from whether the pixels came out right.

The design intent, stated once so the numbers below are readable:

======================  ====================================================
IDLE                    slow breathing; the instrument is at rest
WAKE_DETECTED           a sharp intake — aperture snaps open, orbits kick
LISTENING               aperture wide, waveform live and reacting to the mic
TRANSCRIBING            aperture narrows to a slit; mechanical, steady spin
THINKING                orbits accelerate and diverge; nodes multiply
EXECUTING               everything focuses; the status ring sweeps as progress
SPEAKING                waveform driven by B.O.B.'s own output, warm and even
ERROR                   motion stalls, ring breaks into a slow asymmetric pulse
OFFLINE                 dormant; aperture closed, no orbit motion
======================  ====================================================
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from bob.core.states import BobState
from bob.ui.theme.color import mix
from bob.ui.theme.tokens import Theme


@dataclass(frozen=True, slots=True)
class CoreVisual:
    """Every parameter the animated core needs, for one state.

    Values are normalised (0..1) unless named otherwise, so they can be
    interpolated blindly when the state changes.
    """

    #: Colour the core reads as right now.
    accent: str = "#4FD9E8"

    #: How far the iris blades stand open. 0 = sealed, 1 = fully retracted.
    aperture: float = 0.45

    #: Radians per second for each of the three orbital rings. Signs differ so
    #: the rings counter-rotate, which is what makes it read as an instrument
    #: rather than a spinner.
    orbit_speeds: tuple[float, float, float] = (0.05, -0.032, 0.018)

    #: Ambient breathing depth and period.
    breath_depth: float = 0.06
    breath_period_s: float = 5.2

    #: Data nodes riding the orbits: how many, and how brightly.
    node_density: float = 0.35
    node_brightness: float = 0.55

    #: Radial waveform band. ``waveform_gain`` scales the incoming audio level.
    waveform: bool = False
    waveform_gain: float = 1.0

    #: Outer status ring: full circle, or a sweeping progress arc.
    ring_sweep: bool = False
    ring_thickness: float = 0.5

    #: Glow budget, resolved against :class:`bob.ui.theme.tokens.Glow`.
    glow: str = "soft"

    #: Overall energy — drives inner core luminosity. 0 = dark, 1 = full.
    energy: float = 0.5

    #: Asymmetric wobble. Only ERROR uses this, and only gently.
    unrest: float = 0.0


def _visuals(theme: Theme) -> dict[BobState, CoreVisual]:
    st = theme.palette.status
    return {
        BobState.OFFLINE: CoreVisual(
            accent=st.offline,
            aperture=0.0,
            orbit_speeds=(0.0, 0.0, 0.0),
            breath_depth=0.0,
            node_density=0.0,
            node_brightness=0.0,
            ring_thickness=0.25,
            glow="none",
            energy=0.04,
        ),
        BobState.STARTING: CoreVisual(
            accent=mix(st.offline, st.idle, 0.5),
            aperture=0.2,
            orbit_speeds=(0.14, -0.10, 0.06),
            breath_depth=0.03,
            breath_period_s=1.8,
            node_density=0.2,
            node_brightness=0.4,
            ring_sweep=True,
            glow="soft",
            energy=0.3,
        ),
        BobState.IDLE: CoreVisual(
            accent=st.idle,
            aperture=0.42,
            orbit_speeds=(0.05, -0.032, 0.018),
            breath_depth=0.07,
            breath_period_s=5.2,
            node_density=0.30,
            node_brightness=0.45,
            glow="soft",
            energy=0.42,
        ),
        BobState.WAKE_DETECTED: CoreVisual(
            accent=st.wake,
            aperture=0.92,
            orbit_speeds=(0.34, -0.26, 0.15),
            breath_depth=0.02,
            breath_period_s=1.1,
            node_density=0.55,
            node_brightness=0.95,
            ring_thickness=0.75,
            glow="strong",
            energy=0.95,
        ),
        BobState.LISTENING: CoreVisual(
            accent=st.listening,
            aperture=0.86,
            orbit_speeds=(0.08, -0.05, 0.03),
            breath_depth=0.03,
            breath_period_s=3.0,
            node_density=0.4,
            node_brightness=0.7,
            waveform=True,
            waveform_gain=1.25,
            ring_thickness=0.65,
            glow="medium",
            energy=0.72,
        ),
        BobState.TRANSCRIBING: CoreVisual(
            accent=st.transcribing,
            aperture=0.22,
            orbit_speeds=(0.20, -0.20, 0.20),  # locked ratio: mechanical
            breath_depth=0.015,
            breath_period_s=1.4,
            node_density=0.6,
            node_brightness=0.6,
            ring_sweep=True,
            ring_thickness=0.55,
            glow="soft",
            energy=0.58,
        ),
        BobState.THINKING: CoreVisual(
            accent=st.thinking,
            aperture=0.55,
            orbit_speeds=(0.26, -0.17, 0.41),  # divergent: no shared rhythm
            breath_depth=0.05,
            breath_period_s=2.4,
            node_density=0.95,
            node_brightness=0.8,
            ring_thickness=0.5,
            glow="medium",
            energy=0.78,
        ),
        BobState.EXECUTING: CoreVisual(
            accent=st.executing,
            aperture=0.34,
            orbit_speeds=(0.11, -0.11, 0.055),  # harmonised: everything aligned
            breath_depth=0.02,
            breath_period_s=2.0,
            node_density=0.5,
            node_brightness=0.85,
            ring_sweep=True,
            ring_thickness=0.9,
            glow="medium",
            energy=0.85,
        ),
        BobState.SPEAKING: CoreVisual(
            accent=st.speaking,
            aperture=0.7,
            orbit_speeds=(0.07, -0.045, 0.025),
            breath_depth=0.04,
            breath_period_s=3.4,
            node_density=0.35,
            node_brightness=0.65,
            waveform=True,
            waveform_gain=0.95,
            ring_thickness=0.6,
            glow="medium",
            energy=0.8,
        ),
        BobState.ERROR: CoreVisual(
            accent=st.error,
            aperture=0.15,
            orbit_speeds=(0.012, -0.008, 0.004),  # nearly stalled
            breath_depth=0.09,
            breath_period_s=2.8,
            node_density=0.12,
            node_brightness=0.5,
            ring_thickness=0.7,
            glow="soft",
            energy=0.45,
            unrest=0.5,
        ),
    }


class VisualCatalogue:
    """Resolves a :class:`BobState` to its :class:`CoreVisual`."""

    def __init__(self, theme: Theme) -> None:
        self._theme = theme
        self._table = _visuals(theme)
        self._reduced = theme.reduced_motion

    def for_state(self, state: BobState) -> CoreVisual:
        visual = self._table[state]
        return calm(visual) if self._reduced else visual

    def accent_for(self, state: BobState) -> str:
        return self._table[state].accent


def calm(visual: CoreVisual) -> CoreVisual:
    """Reduced-motion variant: keep meaning, remove movement.

    Colour, aperture and glow still distinguish every state — only the moving
    parts are stilled — so a user who needs reduced motion loses no information.
    """
    return replace(
        visual,
        orbit_speeds=(0.0, 0.0, 0.0),
        breath_depth=0.0,
        waveform=False,
        ring_sweep=False,
        unrest=0.0,
    )


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def blend(a: CoreVisual, b: CoreVisual, t: float) -> CoreVisual:
    """Interpolate between two visuals; ``t=0`` is ``a``, ``t=1`` is ``b``.

    Used to morph the core smoothly when the state machine moves, rather than
    snapping between appearances.
    """
    t = max(0.0, min(1.0, t))
    return CoreVisual(
        accent=mix(a.accent, b.accent, t),
        aperture=_lerp(a.aperture, b.aperture, t),
        orbit_speeds=(
            _lerp(a.orbit_speeds[0], b.orbit_speeds[0], t),
            _lerp(a.orbit_speeds[1], b.orbit_speeds[1], t),
            _lerp(a.orbit_speeds[2], b.orbit_speeds[2], t),
        ),
        breath_depth=_lerp(a.breath_depth, b.breath_depth, t),
        breath_period_s=_lerp(a.breath_period_s, b.breath_period_s, t),
        node_density=_lerp(a.node_density, b.node_density, t),
        node_brightness=_lerp(a.node_brightness, b.node_brightness, t),
        # Booleans switch at the midpoint rather than interpolating.
        waveform=b.waveform if t >= 0.5 else a.waveform,
        waveform_gain=_lerp(a.waveform_gain, b.waveform_gain, t),
        ring_sweep=b.ring_sweep if t >= 0.5 else a.ring_sweep,
        ring_thickness=_lerp(a.ring_thickness, b.ring_thickness, t),
        glow=b.glow if t >= 0.5 else a.glow,
        energy=_lerp(a.energy, b.energy, t),
        unrest=_lerp(a.unrest, b.unrest, t),
    )
