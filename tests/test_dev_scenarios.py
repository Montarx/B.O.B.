"""The scripted demo scenario.

The demo drives the *real* kernel and the *real* state machine, so these tests
double as a check that a full interaction is legal from start to finish.
"""

from __future__ import annotations

import asyncio

import pytest

from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.kernel import Kernel
from bob.core.states import BobState, can_transition
from bob.dev.scenarios import DemoScenario, DemoTurn

from .conftest import Recorder

#: A single fast turn, so tests stay quick.
FAST_TURN = (DemoTurn(utterance="γεια", reply="Ναι", tools=(("app.open", "Spotify"),)),)


@pytest.fixture
async def kernel(settings: Settings, bus: EventBus):
    k = Kernel(settings, bus=bus)
    await k.start()
    yield k
    await k.aclose()


async def test_demo_visits_the_whole_pipeline(kernel: Kernel, recorder: Recorder) -> None:
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=False, speed=40.0)
    await scenario.run()

    visited = [
        BobState(e.new)  # type: ignore[attr-defined]
        for e in recorder.of("state.changed")
    ]
    for expected in (
        BobState.WAKE_DETECTED,
        BobState.LISTENING,
        BobState.TRANSCRIBING,
        BobState.THINKING,
        BobState.EXECUTING,
        BobState.SPEAKING,
    ):
        assert expected in visited, f"demo never reached {expected}"


async def test_demo_only_makes_legal_transitions(kernel: Kernel, recorder: Recorder) -> None:
    """A demo that cheats the state machine would prove nothing."""
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=False, speed=40.0)
    await scenario.run()

    for event in recorder.of("state.changed"):
        old = BobState(event.old)  # type: ignore[attr-defined]
        new = BobState(event.new)  # type: ignore[attr-defined]
        assert can_transition(old, new), f"illegal {old} -> {new}"


async def test_demo_returns_to_idle(kernel: Kernel) -> None:
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=False, speed=40.0)
    await scenario.run()
    assert kernel.state.state is BobState.IDLE


async def test_demo_publishes_a_transcript_and_a_reply(kernel: Kernel, recorder: Recorder) -> None:
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=False, speed=40.0)
    await scenario.run()
    assert recorder.of("stt.transcript_ready")
    assert recorder.of("brain.response_ready")
    assert recorder.of("brain.response_chunk")


async def test_demo_runs_tools_through_events(kernel: Kernel, recorder: Recorder) -> None:
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=False, speed=40.0)
    await scenario.run()
    started = recorder.of("tool.execution_started")
    finished = recorder.of("tool.execution_finished")
    assert len(started) == 1
    assert len(finished) == 1


async def test_demo_emits_audio_levels_for_the_core(kernel: Kernel, recorder: Recorder) -> None:
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=False, speed=40.0)
    await scenario.run()
    levels = recorder.of("audio.level")
    assert levels
    assert all(0.0 <= e.rms <= 1.0 for e in levels)  # type: ignore[attr-defined]
    assert {e.direction for e in levels} == {"input", "output"}  # type: ignore[attr-defined]


async def test_demo_can_be_stopped_early(kernel: Kernel) -> None:
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=True, speed=8.0)
    task = asyncio.create_task(scenario.run())
    await asyncio.sleep(0.05)
    scenario.stop()
    await asyncio.wait_for(task, timeout=5.0)
    assert scenario.stopped
    assert kernel.state.state is BobState.IDLE


async def test_demo_loops_until_stopped(kernel: Kernel, recorder: Recorder) -> None:
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=True, speed=60.0)
    task = asyncio.create_task(scenario.run())
    await asyncio.sleep(0.4)
    scenario.stop()
    await asyncio.wait_for(task, timeout=5.0)
    # A single turn publishes one transcript; looping must publish more.
    assert len(recorder.of("stt.transcript_ready")) >= 2


async def test_demo_recovers_from_a_non_idle_start(kernel: Kernel) -> None:
    await kernel.state.transition(BobState.THINKING, reason="test")
    scenario = DemoScenario(kernel, script=FAST_TURN, loop_forever=False, speed=40.0)
    await scenario.run()
    assert kernel.state.state is BobState.IDLE
