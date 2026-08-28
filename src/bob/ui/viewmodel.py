"""Immutable snapshots of what the shell should display.

The view model is plain Python: no Qt, no kernel imports beyond the state enum.
Widgets receive a snapshot and render it. They never reach back into the kernel
to ask a question, which is what keeps the render path cheap and predictable.

Snapshots are frozen and compared by value, so the shell can skip a repaint when
nothing meaningful changed — important when audio-level events arrive 30 times a
second.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import StrEnum

from bob.core.states import STATUS_TEXT, BobState


class Speaker(StrEnum):
    USER = "user"
    BOB = "bob"
    SYSTEM = "system"


class EntryKind(StrEnum):
    """What a conversation entry represents.

    The conversation is an activity log, not a chat transcript — tool calls and
    status notes live in the same stream as speech, which is what stops it
    looking like a generic chat client.
    """

    MESSAGE = "message"
    TOOL = "tool"
    NOTE = "note"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ConversationEntry:
    """One line in B.O.B.'s activity stream."""

    id: str
    speaker: Speaker
    kind: EntryKind = EntryKind.MESSAGE
    text: str = ""
    #: True while text is still arriving, so the view can show a caret.
    streaming: bool = False
    timestamp: float = field(default_factory=time.time)
    #: Tool entries only.
    tool_name: str = ""
    tool_ok: bool | None = None
    tool_detail: str = ""
    duration_ms: float = 0.0

    def with_text(self, text: str, *, streaming: bool = True) -> ConversationEntry:
        return replace(self, text=text, streaming=streaming)


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """An entry in the "recent activity" rail."""

    id: str
    tool: str
    ok: bool
    risk: str = "low"
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class SystemStats:
    """Mock system telemetry for Phase 1. Real values arrive in Phase 6."""

    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 32.0
    disk_percent: float = 0.0
    network_kbps: float = 0.0
    gpu_percent: float = 0.0


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """What B.O.B. is currently running on, for the model panel."""

    llm: str = "—"
    stt: str = "—"
    tts: str = "—"
    wakeword: str = "—"
    #: True while every provider is still a Phase 0/1 mock.
    simulated: bool = True


@dataclass(frozen=True, slots=True)
class TaskInfo:
    """The current multi-step task, if any."""

    title: str = ""
    detail: str = ""
    #: 0..1, or ``None`` for indeterminate work.
    progress: float | None = None
    active: bool = False


@dataclass(frozen=True, slots=True)
class MicrophoneInfo:
    """What the UI shows about audio input."""

    available: bool = False
    listening: bool = False
    device: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    """A HIGH/MEDIUM risk action waiting on the user."""

    call_id: str
    tool: str
    risk: str
    summary: str


@dataclass(frozen=True, slots=True)
class ShellViewModel:
    """Everything the main window renders, in one comparable value."""

    state: BobState = BobState.OFFLINE
    status_text: str = STATUS_TEXT[BobState.OFFLINE]
    #: The Greek line shown under the core, e.g. "Σε ακούω...".
    caption: str = ""
    conversation: tuple[ConversationEntry, ...] = ()
    actions: tuple[ActionRecord, ...] = ()
    task: TaskInfo = field(default_factory=TaskInfo)
    system: SystemStats = field(default_factory=SystemStats)
    providers: ProviderInfo = field(default_factory=ProviderInfo)
    confirmation: PendingConfirmation | None = None
    microphone: MicrophoneInfo = field(default_factory=MicrophoneInfo)
    #: Live transcript being decoded; replaced by the final one.
    partial_transcript: str = ""
    error: str = ""
    demo_running: bool = False
    #: True while the kernel is reachable; the shell greys out input otherwise.
    connected: bool = False

    @property
    def input_enabled(self) -> bool:
        """Typing is allowed whenever B.O.B. is not mid-thought."""
        return self.connected and self.state in {
            BobState.IDLE,
            BobState.LISTENING,
            BobState.SPEAKING,
        }

    @property
    def can_listen(self) -> bool:
        """The microphone control is usable only from IDLE or while listening."""
        return self.connected and self.state in {BobState.IDLE, BobState.LISTENING}
