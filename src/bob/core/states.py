"""B.O.B.'s lifecycle states and the legal transitions between them.

The transition table is data, not scattered ``if`` statements. Anything not listed
here is a bug, and the state machine will say so instead of silently proceeding.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class BobState(StrEnum):
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    IDLE = "IDLE"
    WAKE_DETECTED = "WAKE_DETECTED"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


#: States reachable from *any* state — failure and shutdown are always allowed.
UNIVERSAL_TARGETS: frozenset[BobState] = frozenset({BobState.ERROR, BobState.OFFLINE})

_TRANSITIONS: dict[BobState, frozenset[BobState]] = {
    BobState.OFFLINE: frozenset({BobState.STARTING}),
    BobState.STARTING: frozenset({BobState.IDLE}),
    # From IDLE we can be woken by voice, by push-to-talk, or by typed text.
    BobState.IDLE: frozenset({BobState.WAKE_DETECTED, BobState.LISTENING, BobState.THINKING}),
    # WAKE_DETECTED is a short acknowledgement window; it may time out back to IDLE.
    BobState.WAKE_DETECTED: frozenset({BobState.LISTENING, BobState.IDLE}),
    # LISTENING returns to IDLE when VAD hears nothing at all.
    BobState.LISTENING: frozenset({BobState.TRANSCRIBING, BobState.IDLE}),
    # An empty transcript goes back to IDLE rather than bothering the LLM.
    BobState.TRANSCRIBING: frozenset({BobState.THINKING, BobState.IDLE}),
    # THINKING may call a tool, answer directly, or decide nothing is needed.
    BobState.THINKING: frozenset({BobState.EXECUTING, BobState.SPEAKING, BobState.IDLE}),
    # After a tool runs we usually think again with the result in hand.
    BobState.EXECUTING: frozenset({BobState.THINKING, BobState.SPEAKING, BobState.IDLE}),
    # SPEAKING -> LISTENING is the barge-in path: the user interrupts B.O.B.
    BobState.SPEAKING: frozenset({BobState.IDLE, BobState.LISTENING}),
    BobState.ERROR: frozenset({BobState.IDLE, BobState.STARTING}),
}

#: Read-only view of the transition table.
TRANSITIONS: Mapping[BobState, frozenset[BobState]] = MappingProxyType(
    {state: targets | UNIVERSAL_TARGETS for state, targets in _TRANSITIONS.items()}
)

#: States during which B.O.B. is actively working on the user's behalf.
BUSY_STATES: frozenset[BobState] = frozenset(
    {
        BobState.LISTENING,
        BobState.TRANSCRIBING,
        BobState.THINKING,
        BobState.EXECUTING,
        BobState.SPEAKING,
    }
)

#: What the UI shows for each state. Greek is spoken; the HUD stays English.
STATUS_TEXT: Mapping[BobState, str] = MappingProxyType(
    {
        BobState.OFFLINE: "CORE // OFFLINE",
        BobState.STARTING: "CORE // BOOTING",
        BobState.IDLE: "CORE // ONLINE",
        BobState.WAKE_DETECTED: "AWAKE",
        BobState.LISTENING: "LISTENING",
        BobState.TRANSCRIBING: "TRANSCRIBING",
        BobState.THINKING: "THINKING",
        BobState.EXECUTING: "EXECUTING",
        BobState.SPEAKING: "SPEAKING",
        BobState.ERROR: "FAULT",
    }
)


def can_transition(current: BobState, target: BobState) -> bool:
    """Return whether ``current -> target`` is permitted."""
    return target in TRANSITIONS[current]
