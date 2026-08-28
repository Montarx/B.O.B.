"""State to visual behaviour.

The brief asks that animations communicate state rather than decorate. These
tests assert exactly that: every state must be distinguishable, and the
distinctions must survive reduced-motion mode.
"""

from __future__ import annotations

import pytest

from bob.core.states import BobState
from bob.ui.theme.tokens import DEFAULT_THEME
from bob.ui.visual import CoreVisual, VisualCatalogue, blend, calm


@pytest.fixture
def catalogue() -> VisualCatalogue:
    return VisualCatalogue(DEFAULT_THEME)


def test_every_state_has_a_visual(catalogue: VisualCatalogue) -> None:
    for state in BobState:
        assert isinstance(catalogue.for_state(state), CoreVisual)


def test_every_state_is_visually_distinguishable(catalogue: VisualCatalogue) -> None:
    """No two states may look identical — that would make the core decoration."""
    seen: dict[tuple[object, ...], BobState] = {}
    for state in BobState:
        v = catalogue.for_state(state)
        key = (v.accent, round(v.aperture, 2), round(v.energy, 2), v.waveform, v.ring_sweep)
        assert key not in seen, f"{state} looks identical to {seen[key]}"
        seen[key] = state


def test_offline_is_dormant(catalogue: VisualCatalogue) -> None:
    v = catalogue.for_state(BobState.OFFLINE)
    assert v.orbit_speeds == (0.0, 0.0, 0.0)
    assert v.aperture == 0.0  # iris sealed
    assert v.energy < 0.1
    assert v.glow == "none"


def test_wake_is_the_sharpest_response(catalogue: VisualCatalogue) -> None:
    wake = catalogue.for_state(BobState.WAKE_DETECTED)
    idle = catalogue.for_state(BobState.IDLE)
    assert wake.aperture > idle.aperture
    assert wake.energy > idle.energy
    assert abs(wake.orbit_speeds[0]) > abs(idle.orbit_speeds[0])
    assert wake.glow == "strong"


def test_only_listening_and_speaking_show_a_waveform(
    catalogue: VisualCatalogue,
) -> None:
    """The waveform means audio. It must not appear when there is no audio."""
    with_waveform = {s for s in BobState if catalogue.for_state(s).waveform}
    assert with_waveform == {BobState.LISTENING, BobState.SPEAKING}


def test_only_progress_states_sweep_the_ring(catalogue: VisualCatalogue) -> None:
    sweeping = {s for s in BobState if catalogue.for_state(s).ring_sweep}
    assert sweeping == {
        BobState.STARTING,
        BobState.TRANSCRIBING,
        BobState.EXECUTING,
    }


def test_thinking_is_busier_than_idle(catalogue: VisualCatalogue) -> None:
    thinking = catalogue.for_state(BobState.THINKING)
    idle = catalogue.for_state(BobState.IDLE)
    assert thinking.node_density > idle.node_density
    assert max(abs(s) for s in thinking.orbit_speeds) > max(abs(s) for s in idle.orbit_speeds)


def test_thinking_orbits_are_divergent(catalogue: VisualCatalogue) -> None:
    """THINKING should have no shared rhythm; EXECUTING should be harmonised."""
    thinking = catalogue.for_state(BobState.THINKING).orbit_speeds
    executing = catalogue.for_state(BobState.EXECUTING).orbit_speeds
    assert abs(abs(thinking[0]) - abs(thinking[1])) > 0.05
    assert abs(abs(executing[0]) - abs(executing[1])) < 0.01


def test_error_is_restrained_not_flashing(catalogue: VisualCatalogue) -> None:
    """A flashing core would be ugly and an accessibility problem."""
    v = catalogue.for_state(BobState.ERROR)
    assert v.unrest > 0.0
    assert v.unrest <= 0.6
    assert max(abs(s) for s in v.orbit_speeds) < 0.05  # motion stalls
    assert v.accent == DEFAULT_THEME.palette.status.error


def test_error_is_the_only_unsettled_state(catalogue: VisualCatalogue) -> None:
    unsettled = {s for s in BobState if catalogue.for_state(s).unrest > 0}
    assert unsettled == {BobState.ERROR}


def test_accent_matches_the_status_palette(catalogue: VisualCatalogue) -> None:
    status = DEFAULT_THEME.palette.status
    assert catalogue.accent_for(BobState.LISTENING) == status.listening
    assert catalogue.accent_for(BobState.THINKING) == status.thinking
    assert catalogue.accent_for(BobState.EXECUTING) == status.executing


# -- reduced motion ---------------------------------------------------------


def test_calm_removes_movement_but_keeps_meaning() -> None:
    lively = VisualCatalogue(DEFAULT_THEME).for_state(BobState.THINKING)
    still = calm(lively)
    assert still.orbit_speeds == (0.0, 0.0, 0.0)
    assert still.breath_depth == 0.0
    assert not still.waveform
    # Meaning survives: colour, aperture and energy still identify the state.
    assert still.accent == lively.accent
    assert still.aperture == lively.aperture
    assert still.energy == lively.energy


def test_reduced_motion_states_remain_distinguishable() -> None:
    """Someone using reduced motion must lose no information."""
    catalogue = VisualCatalogue(DEFAULT_THEME.with_reduced_motion(True))
    keys = {
        (catalogue.for_state(s).accent, round(catalogue.for_state(s).aperture, 2)) for s in BobState
    }
    assert len(keys) == len(BobState)


def test_reduced_motion_catalogue_is_still() -> None:
    catalogue = VisualCatalogue(DEFAULT_THEME.with_reduced_motion(True))
    for state in BobState:
        assert catalogue.for_state(state).orbit_speeds == (0.0, 0.0, 0.0)


# -- blending ---------------------------------------------------------------


def test_blend_endpoints_are_exact() -> None:
    a = CoreVisual(accent="#000000", aperture=0.0, energy=0.0)
    b = CoreVisual(accent="#FFFFFF", aperture=1.0, energy=1.0)
    assert blend(a, b, 0.0).accent == a.accent
    assert blend(a, b, 1.0).aperture == pytest.approx(1.0)


def test_blend_interpolates_continuously() -> None:
    a = CoreVisual(aperture=0.0, energy=0.0)
    b = CoreVisual(aperture=1.0, energy=1.0)
    mid = blend(a, b, 0.5)
    assert mid.aperture == pytest.approx(0.5)
    assert mid.energy == pytest.approx(0.5)


def test_blend_clamps_out_of_range_t() -> None:
    a = CoreVisual(aperture=0.0)
    b = CoreVisual(aperture=1.0)
    assert blend(a, b, -5.0).aperture == pytest.approx(0.0)
    assert blend(a, b, 5.0).aperture == pytest.approx(1.0)


def test_blend_switches_booleans_at_the_midpoint() -> None:
    """Booleans cannot interpolate, so they flip once, halfway."""
    a = CoreVisual(waveform=False)
    b = CoreVisual(waveform=True)
    assert blend(a, b, 0.49).waveform is False
    assert blend(a, b, 0.51).waveform is True
