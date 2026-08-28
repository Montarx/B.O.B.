"""UI intents — what the user asked the application to do.

Widgets never act. They emit an intent, the shell forwards it to the bridge,
and the bridge turns it into a kernel call on the kernel thread. This is what
keeps rule 14 ("no business logic in widgets") enforceable rather than merely
encouraged: a widget has no way to reach a model, a tool, or a device.
"""

from __future__ import annotations

from dataclasses import dataclass

from bob.core.states import BobState


@dataclass(frozen=True, slots=True)
class SubmitText:
    """The user typed something and pressed enter."""

    text: str


@dataclass(frozen=True, slots=True)
class RequestState:
    """Developer tooling asked B.O.B. to move to a state."""

    state: BobState


@dataclass(frozen=True, slots=True)
class RunDemo:
    """Start or stop the scripted demonstration scenario."""

    running: bool = True


@dataclass(frozen=True, slots=True)
class ConfirmAction:
    """Answer to a pending confirmation request."""

    call_id: str
    approved: bool


@dataclass(frozen=True, slots=True)
class CancelCurrent:
    """Stop whatever B.O.B. is doing and return to idle."""


@dataclass(frozen=True, slots=True)
class ToggleListening:
    """Start or stop the microphone.

    Temporary infrastructure: until the wake word lands in Phase 5, this is how
    listening is triggered. The pipeline underneath is the real one.
    """

    listening: bool = True


Intent = SubmitText | RequestState | RunDemo | ConfirmAction | CancelCurrent | ToggleListening
