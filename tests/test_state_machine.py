"""State machine guarantees.

The point of these tests is that B.O.B. can never end up in an inconsistent state
because someone flipped a boolean in the wrong place.
"""

from __future__ import annotations

import pytest

from bob.core.bus import EventBus
from bob.core.errors import IllegalTransitionError
from bob.core.state_machine import StateMachine
from bob.core.states import (
    STATUS_TEXT,
    TRANSITIONS,
    BobState,
    can_transition,
)

from .conftest import Recorder


async def test_starts_offline(bus: EventBus) -> None:
    assert StateMachine(bus).state is BobState.OFFLINE


async def test_normal_boot_path(bus: EventBus, recorder: Recorder) -> None:
    sm = StateMachine(bus)
    await sm.transition(BobState.STARTING)
    await sm.transition(BobState.IDLE)
    assert sm.state is BobState.IDLE
    assert recorder.types() == ["state.changed", "state.changed"]


async def test_illegal_transition_raises_and_does_not_change_state(
    bus: EventBus,
) -> None:
    sm = StateMachine(bus)
    with pytest.raises(IllegalTransitionError):
        await sm.transition(BobState.SPEAKING)
    assert sm.state is BobState.OFFLINE


async def test_transition_publishes_old_and_new(bus: EventBus, recorder: Recorder) -> None:
    sm = StateMachine(bus)
    await sm.transition(BobState.STARTING, reason="boot")
    event = recorder.of("state.changed")[0]
    assert event.old == "OFFLINE"  # type: ignore[attr-defined]
    assert event.new == "STARTING"  # type: ignore[attr-defined]
    assert event.reason == "boot"  # type: ignore[attr-defined]


async def test_same_state_transition_is_a_silent_noop(bus: EventBus, recorder: Recorder) -> None:
    sm = StateMachine(bus, initial=BobState.IDLE)
    await sm.transition(BobState.IDLE)
    assert recorder.of("state.changed") == []


async def test_error_is_reachable_from_every_state(bus: EventBus) -> None:
    for state in BobState:
        if state is BobState.ERROR:
            continue
        sm = StateMachine(bus, initial=state)
        await sm.to_error("boom")
        assert sm.state is BobState.ERROR


async def test_offline_is_reachable_from_every_state(bus: EventBus) -> None:
    for state in BobState:
        if state is BobState.OFFLINE:
            continue
        sm = StateMachine(bus, initial=state)
        await sm.transition(BobState.OFFLINE, reason="shutdown")
        assert sm.state is BobState.OFFLINE


async def test_barge_in_path_exists() -> None:
    """SPEAKING -> LISTENING is what makes interrupting B.O.B. possible."""
    assert can_transition(BobState.SPEAKING, BobState.LISTENING)


async def test_tool_result_can_feed_back_into_thinking() -> None:
    """Multi-step tasks need EXECUTING -> THINKING."""
    assert can_transition(BobState.EXECUTING, BobState.THINKING)


async def test_wake_word_window_can_time_out() -> None:
    assert can_transition(BobState.WAKE_DETECTED, BobState.IDLE)


def test_every_state_has_a_transition_entry_and_status_text() -> None:
    for state in BobState:
        assert state in TRANSITIONS, f"{state} missing from transition table"
        assert state in STATUS_TEXT, f"{state} missing status text"


def test_no_state_is_a_dead_end() -> None:
    for state, targets in TRANSITIONS.items():
        assert targets - {state}, f"{state} has no way out"


async def test_history_is_recorded(bus: EventBus) -> None:
    sm = StateMachine(bus)
    await sm.transition(BobState.STARTING, reason="boot")
    await sm.transition(BobState.IDLE, reason="ready")
    assert [s for s, _ in sm.history] == [
        BobState.OFFLINE,
        BobState.STARTING,
        BobState.IDLE,
    ]
