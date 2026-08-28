"""Scripted scenarios that drive the kernel without any real AI.

The demo walks B.O.B. through a complete interaction —

    IDLE → WAKE_DETECTED → LISTENING → TRANSCRIBING → THINKING
         → EXECUTING → SPEAKING → IDLE

— publishing the same events the real pipeline will publish in Phases 2-6, at
roughly the same pace. That means the UI is exercised through its actual code
path, not through a special "demo mode" that bypasses it.

This module contains no Qt. It runs on the kernel loop like everything else.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from bob.core.events import (
    AudioLevel,
    ResponseChunk,
    ResponseReady,
    SpeechEnded,
    SpeechStarted,
    ToolExecutionFinished,
    ToolExecutionStarted,
    TranscriptReady,
    WakeWordDetected,
)
from bob.core.kernel import Kernel
from bob.core.states import BobState

_log = logging.getLogger("bob.app.demo")


@dataclass(frozen=True, slots=True)
class DemoTurn:
    """One scripted exchange."""

    utterance: str
    reply: str
    tools: tuple[tuple[str, str], ...] = ()  # (tool name, summary)


#: Written to sound like the persona file: relaxed, Greek, short.
DEFAULT_SCRIPT: tuple[DemoTurn, ...] = (
    DemoTurn(
        utterance="Μπομπ, άνοιξε Spotify και Discord.",
        reply="Ναι ρε, ένα δευτερόλεπτο. Έγινε, και τα δύο.",
        tools=(("app.open", "Spotify"), ("app.open", "Discord")),
    ),
    DemoTurn(
        utterance="Τι τρώει όλη τη RAM;",
        reply="Ο Chrome, 4.2 GB με 23 tabs. Θες να κλείσω τα background;",
        tools=(("system.processes", "top 5 by memory"),),
    ),
    DemoTurn(
        utterance="Θυμήσου ότι προτιμάω σκούρο θέμα.",
        reply="Το κράτησα.",
        tools=(("memory.remember", "προτίμηση: σκούρο θέμα"),),
    ),
)

#: How long each stage lingers, in seconds. Tuned to feel like a real turn.
TIMINGS: dict[str, float] = {
    "wake": 0.5,
    "listen_per_word": 0.16,
    "transcribe": 0.9,
    "think": 1.1,
    "tool": 0.7,
    "speak_per_word": 0.19,
    "settle": 1.4,
}


class DemoScenario:
    """Drives one or more scripted turns through the real kernel."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        script: Sequence[DemoTurn] = DEFAULT_SCRIPT,
        loop_forever: bool = True,
        speed: float = 1.0,
    ) -> None:
        self._kernel = kernel
        self._script = list(script)
        self._loop_forever = loop_forever
        self._speed = max(0.05, speed)
        self._stop = asyncio.Event()

    def stop(self) -> None:
        """Ask the scenario to finish after the current step."""
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # -- main loop -------------------------------------------------------

    async def run(self) -> None:
        """Run the script, returning B.O.B. to IDLE whatever happens."""
        try:
            while not self._stop.is_set():
                for turn in self._script:
                    if self._stop.is_set():
                        break
                    await self._play(turn)
                if not self._loop_forever:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("demo scenario failed")
        finally:
            await self._safe_idle()

    async def _play(self, turn: DemoTurn) -> None:
        state = self._kernel.state
        bus = self._kernel.bus

        # -- wake ---------------------------------------------------------
        await self._ensure_idle()
        await state.transition(BobState.WAKE_DETECTED, reason="demo")
        await bus.publish(WakeWordDetected(source="demo", keyword="μπομπ"))
        if await self._sleep(TIMINGS["wake"]):
            return

        # -- listen, with a plausible audio envelope -----------------------
        await state.transition(BobState.LISTENING, reason="demo")
        await bus.publish(SpeechStarted(source="demo"))
        words = turn.utterance.split()
        for index in range(len(words) * 2):
            if self._stop.is_set():
                return
            await bus.publish(
                AudioLevel(source="demo", rms=self._envelope(index), direction="input")
            )
            if await self._sleep(TIMINGS["listen_per_word"] / 2):
                return
        await bus.publish(
            SpeechEnded(source="demo", duration_s=len(words) * TIMINGS["listen_per_word"])
        )
        await bus.publish(AudioLevel(source="demo", rms=0.0, direction="input"))

        # -- transcribe ----------------------------------------------------
        await state.transition(BobState.TRANSCRIBING, reason="demo")
        if await self._sleep(TIMINGS["transcribe"]):
            return
        await bus.publish(TranscriptReady(source="demo", text=turn.utterance))

        # -- think ---------------------------------------------------------
        await state.transition(BobState.THINKING, reason="demo")
        if await self._sleep(TIMINGS["think"]):
            return

        # -- execute -------------------------------------------------------
        for index, (tool, summary) in enumerate(turn.tools):
            if self._stop.is_set():
                return
            if index == 0:
                await state.transition(BobState.EXECUTING, reason="demo")
            call_id = f"demo-{tool}-{index}"
            await bus.publish(
                ToolExecutionStarted(source="demo", tool=tool, call_id=call_id, risk="low")
            )
            if await self._sleep(TIMINGS["tool"]):
                return
            await bus.publish(
                ToolExecutionFinished(
                    source="demo",
                    tool=tool,
                    call_id=call_id,
                    ok=True,
                    duration_ms=TIMINGS["tool"] * 1000,
                    summary=summary,
                )
            )
        if turn.tools:
            await state.transition(BobState.THINKING, reason="demo")
            if await self._sleep(0.4):
                return

        # -- speak, streaming word by word ---------------------------------
        await state.transition(BobState.SPEAKING, reason="demo")
        reply_words = turn.reply.split()
        for index, word in enumerate(reply_words):
            if self._stop.is_set():
                return
            await bus.publish(ResponseChunk(source="demo", text=word + " "))
            await bus.publish(
                AudioLevel(source="demo", rms=self._envelope(index, 0.55), direction="output")
            )
            if await self._sleep(TIMINGS["speak_per_word"]):
                return
        await bus.publish(ResponseReady(source="demo", text=turn.reply))
        await bus.publish(AudioLevel(source="demo", rms=0.0, direction="output"))

        # -- settle ---------------------------------------------------------
        await state.transition(BobState.IDLE, reason="demo")
        await self._sleep(TIMINGS["settle"])

    # -- helpers ---------------------------------------------------------

    def _envelope(self, index: int, base: float = 0.62) -> float:
        """A speech-like amplitude: a slow swell with per-syllable variation."""
        swell = 0.5 + 0.5 * math.sin(index * 0.5)
        return max(0.05, min(1.0, base * swell + random.uniform(-0.12, 0.18)))

    async def _sleep(self, seconds: float) -> bool:
        """Sleep unless asked to stop. Returns True if the scenario should end."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, seconds / self._speed))
        except TimeoutError:
            return False
        return True

    async def _ensure_idle(self) -> None:
        machine = self._kernel.state
        if machine.state is not BobState.IDLE:
            await self._safe_idle()

    async def _safe_idle(self) -> None:
        """Return to IDLE by a legal route, ignoring a machine already there."""
        from bob.core.states import find_transition_path

        machine = self._kernel.state
        path = find_transition_path(machine.state, BobState.IDLE) or []
        for step in path:
            await machine.transition(step, reason="demo cleanup")
