"""The Greek line B.O.B. shows under his core.

Kept apart from the view model so the wording is easy to find and change, and so
it can be translated later without touching presentation logic. These are UI
strings, distinct from B.O.B.'s spoken personality in ``config/personas/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from bob.core.states import BobState

#: Short, conversational, lower-case. This is B.O.B. talking, not a system label.
STATE_CAPTIONS: Mapping[BobState, str] = MappingProxyType(
    {
        BobState.OFFLINE: "Εκτός λειτουργίας",
        BobState.STARTING: "Ξεκινάω...",
        BobState.IDLE: "Τι θέλεις να κάνουμε;",
        BobState.WAKE_DETECTED: "Ναι;",
        BobState.LISTENING: "Σε ακούω...",
        BobState.TRANSCRIBING: "Κατάλαβα, ένα λεπτό...",
        BobState.THINKING: "Σκέφτομαι...",
        BobState.EXECUTING: "Το κάνω...",
        BobState.SPEAKING: "...",
        BobState.ERROR: "Κάτι πήγε στραβά.",
    }
)

#: Shown in the activity rail when nothing has happened yet.
EMPTY_ACTIVITY = "Καμία ενέργεια ακόμα"
EMPTY_CONVERSATION = "Πες μου κάτι για να ξεκινήσουμε"
NO_TASK = "Καμία ενεργή εργασία"
DONE = "Έγινε."


def caption_for(state: BobState) -> str:
    return STATE_CAPTIONS[state]
