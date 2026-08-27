"""The single source of truth for what B.O.B. is doing right now.

Only one component drives this machine (the orchestrator). Everything else reads
:attr:`StateMachine.state` or listens for :class:`StateChanged` on the bus. There
are no ``is_listening`` / ``is_thinking`` booleans anywhere in the codebase.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from bob.core.bus import EventBus
from bob.core.errors import IllegalTransitionError
from bob.core.events import StateChanged
from bob.core.states import TRANSITIONS, BobState, can_transition

_log = logging.getLogger("bob.app.state")

StateObserver = Callable[[BobState, BobState], Awaitable[None]]


class StateMachine:
    """Guarded state container that announces every change on the event bus."""

    def __init__(
        self,
        bus: EventBus,
        *,
        initial: BobState = BobState.OFFLINE,
        source: str = "state_machine",
    ) -> None:
        self._bus = bus
        self._state = initial
        self._source = source
        self._entered_at = time.monotonic()
        self._history: list[tuple[BobState, str]] = [(initial, "init")]
        self._lock = asyncio.Lock()

    # -- reading ---------------------------------------------------------

    @property
    def state(self) -> BobState:
        return self._state

    @property
    def time_in_state(self) -> float:
        """Seconds spent in the current state."""
        return time.monotonic() - self._entered_at

    @property
    def history(self) -> list[tuple[BobState, str]]:
        return list(self._history)

    def can(self, target: BobState) -> bool:
        return can_transition(self._state, target)

    def allowed_targets(self) -> frozenset[BobState]:
        return TRANSITIONS[self._state]

    # -- writing ---------------------------------------------------------

    async def transition(self, target: BobState, *, reason: str = "") -> BobState:
        """Move to ``target``.

        Raises :class:`IllegalTransitionError` if the transition table forbids it.
        A no-op transition (``target`` == current state) is allowed and silent, so
        callers may assert a state without checking first.
        """
        async with self._lock:
            current = self._state
            if target is current:
                return current
            if not can_transition(current, target):
                _log.warning("rejected transition %s -> %s (%s)", current, target, reason)
                raise IllegalTransitionError(current, target)

            self._state = target
            self._entered_at = time.monotonic()
            self._history.append((target, reason))
            if len(self._history) > 200:
                del self._history[:100]

        _log.info("state %s -> %s%s", current, target, f" ({reason})" if reason else "")
        await self._bus.publish(
            StateChanged(
                source=self._source,
                old=current.value,
                new=target.value,
                reason=reason,
            )
        )
        return target

    async def to_error(self, reason: str) -> BobState:
        """Convenience path into ERROR, which is reachable from every state."""
        return await self.transition(BobState.ERROR, reason=reason)

    def __repr__(self) -> str:
        return f"<StateMachine {self._state} for {self.time_in_state:.1f}s>"
