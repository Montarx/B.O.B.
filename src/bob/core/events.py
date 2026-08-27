"""Event definitions.

Events are **facts about things that have already happened**. They are immutable,
carry no behaviour, and are broadcast to any number of uninterested-in-each-other
subscribers (UI, logging, audit, metrics).

Events are deliberately *not* used for request/response control flow. When the
orchestrator needs a result it calls a provider directly and awaits it; it then
publishes an event describing what happened. Mixing the two is how event-driven
systems become untraceable.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    """Every event kind B.O.B. can broadcast."""

    # -- lifecycle -------------------------------------------------------
    KERNEL_STARTING = "kernel.starting"
    KERNEL_READY = "kernel.ready"
    KERNEL_STOPPING = "kernel.stopping"
    STATE_CHANGED = "state.changed"

    # -- audio in --------------------------------------------------------
    WAKE_WORD_DETECTED = "audio.wake_word_detected"
    SPEECH_STARTED = "audio.speech_started"
    SPEECH_ENDED = "audio.speech_ended"
    BARGE_IN_DETECTED = "audio.barge_in_detected"
    AUDIO_LEVEL = "audio.level"

    # -- understanding ---------------------------------------------------
    TRANSCRIPT_READY = "stt.transcript_ready"
    THINKING_STARTED = "brain.thinking_started"
    RESPONSE_CHUNK = "brain.response_chunk"
    RESPONSE_READY = "brain.response_ready"

    # -- acting ----------------------------------------------------------
    CONFIRMATION_REQUESTED = "tool.confirmation_requested"
    TOOL_EXECUTION_STARTED = "tool.execution_started"
    TOOL_EXECUTION_FINISHED = "tool.execution_finished"

    # -- audio out -------------------------------------------------------
    SPEECH_OUTPUT_STARTED = "tts.output_started"
    SPEECH_OUTPUT_FINISHED = "tts.output_finished"

    # -- problems --------------------------------------------------------
    ERROR_OCCURRED = "error.occurred"


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Base event. Subclasses add payload fields; all of them stay immutable."""

    type: EventType
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"

    def describe(self) -> str:
        """Short human-readable line, used by the log subscriber."""
        return self.type.value


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class StateChanged(Event):
    type: EventType = EventType.STATE_CHANGED
    old: str
    new: str
    reason: str = ""

    def describe(self) -> str:
        suffix = f" ({self.reason})" if self.reason else ""
        return f"{self.old} -> {self.new}{suffix}"


# --------------------------------------------------------------------------
# Audio in
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class WakeWordDetected(Event):
    type: EventType = EventType.WAKE_WORD_DETECTED
    keyword: str
    confidence: float = 1.0


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechStarted(Event):
    type: EventType = EventType.SPEECH_STARTED


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechEnded(Event):
    type: EventType = EventType.SPEECH_ENDED
    duration_s: float = 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class BargeInDetected(Event):
    """The user started talking while B.O.B. was speaking."""

    type: EventType = EventType.BARGE_IN_DETECTED


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioLevel(Event):
    """Cheap, high-frequency signal used by the UI to drive the core animation."""

    type: EventType = EventType.AUDIO_LEVEL
    rms: float
    direction: str = "input"  # "input" | "output"


# --------------------------------------------------------------------------
# Understanding
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class TranscriptReady(Event):
    type: EventType = EventType.TRANSCRIPT_READY
    text: str
    language: str = "el"
    confidence: float = 1.0

    def describe(self) -> str:
        return f"[{self.language}] {self.text!r}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ThinkingStarted(Event):
    type: EventType = EventType.THINKING_STARTED
    prompt_preview: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseChunk(Event):
    """One streamed fragment of B.O.B.'s reply (token / sentence)."""

    type: EventType = EventType.RESPONSE_CHUNK
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseReady(Event):
    type: EventType = EventType.RESPONSE_READY
    text: str

    def describe(self) -> str:
        return self.text[:120]


# --------------------------------------------------------------------------
# Acting
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmationRequested(Event):
    type: EventType = EventType.CONFIRMATION_REQUESTED
    tool: str
    risk: str
    summary: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolExecutionStarted(Event):
    type: EventType = EventType.TOOL_EXECUTION_STARTED
    tool: str
    call_id: str
    risk: str

    def describe(self) -> str:
        return f"{self.tool} [{self.risk}]"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolExecutionFinished(Event):
    type: EventType = EventType.TOOL_EXECUTION_FINISHED
    tool: str
    call_id: str
    ok: bool
    duration_ms: float
    summary: str = ""

    def describe(self) -> str:
        status = "ok" if self.ok else "FAILED"
        return f"{self.tool} {status} in {self.duration_ms:.0f}ms"


# --------------------------------------------------------------------------
# Audio out
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechOutputStarted(Event):
    type: EventType = EventType.SPEECH_OUTPUT_STARTED
    text: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechOutputFinished(Event):
    type: EventType = EventType.SPEECH_OUTPUT_FINISHED
    interrupted: bool = False


# --------------------------------------------------------------------------
# Problems
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorOccurred(Event):
    type: EventType = EventType.ERROR_OCCURRED
    message: str
    component: str = "unknown"
    fatal: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        return f"{self.component}: {self.message}"
