"""Turns kernel events into view-model snapshots.

The presenter is the whole of the shell's "business logic", and it is plain
Python — no Qt, no threads, no I/O. That makes the interesting behaviour
(streaming assembly, tool grouping, activity capping) testable by feeding it
events and reading the snapshot back.

It is intentionally a *reducer*: events in, immutable snapshot out. It never
calls the kernel; user actions travel the other way, as intents.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace

from bob.core.events import (
    ConfirmationRequested,
    ErrorOccurred,
    Event,
    EventType,
    ResponseChunk,
    ResponseReady,
    StateChanged,
    ToolExecutionFinished,
    ToolExecutionStarted,
    TranscriptReady,
)
from bob.core.states import STATUS_TEXT, BobState
from bob.ui.captions import caption_for
from bob.ui.viewmodel import (
    ActionRecord,
    ConversationEntry,
    EntryKind,
    PendingConfirmation,
    ProviderInfo,
    ShellViewModel,
    Speaker,
    SystemStats,
    TaskInfo,
)

#: Hard caps. The shell keeps a bounded window; the audit log is the real record.
MAX_CONVERSATION = 80
MAX_ACTIONS = 24

ViewModelListener = Callable[[ShellViewModel], None]


class ShellPresenter:
    """Reduces the kernel event stream into a :class:`ShellViewModel`."""

    def __init__(self, *, on_change: ViewModelListener | None = None) -> None:
        self._vm = ShellViewModel()
        self._listener = on_change
        #: Id of the assistant entry currently receiving streamed text.
        self._streaming_id: str | None = None
        #: Maps a tool call id to its conversation entry, so the finish event
        #: can update the entry the start event created.
        self._tool_entries: dict[str, str] = {}

    # -- reading ---------------------------------------------------------

    @property
    def view_model(self) -> ShellViewModel:
        return self._vm

    def set_listener(self, listener: ViewModelListener) -> None:
        self._listener = listener

    # -- event intake ----------------------------------------------------

    def handle(self, event: Event) -> bool:
        """Apply one event. Returns whether the view model actually changed."""
        before = self._vm
        match event:
            case StateChanged():
                self._on_state(event)
            case TranscriptReady():
                self._on_transcript(event)
            case ResponseChunk():
                self._on_chunk(event)
            case ResponseReady():
                self._on_response(event)
            case ToolExecutionStarted():
                self._on_tool_started(event)
            case ToolExecutionFinished():
                self._on_tool_finished(event)
            case ConfirmationRequested():
                self._on_confirmation(event)
            case ErrorOccurred():
                self._on_error(event)
            case _:
                self._on_lifecycle(event)
        changed = self._vm != before
        if changed and self._listener is not None:
            self._listener(self._vm)
        return changed

    # -- individual reducers ---------------------------------------------

    def _on_state(self, event: StateChanged) -> None:
        state = BobState(event.new)
        self._vm = replace(
            self._vm,
            state=state,
            status_text=STATUS_TEXT[state],
            caption=caption_for(state),
            connected=state is not BobState.OFFLINE,
            # Leaving ERROR clears the banner; entering any other state keeps it.
            error="" if state is not BobState.ERROR else self._vm.error,
        )
        if state in {BobState.IDLE, BobState.OFFLINE}:
            self._vm = replace(self._vm, task=TaskInfo())
            self._finish_streaming()

    def _on_transcript(self, event: TranscriptReady) -> None:
        if not event.text.strip():
            return
        self._append(
            ConversationEntry(
                id=uuid.uuid4().hex[:8],
                speaker=Speaker.USER,
                kind=EntryKind.MESSAGE,
                text=event.text,
            )
        )

    def _on_chunk(self, event: ResponseChunk) -> None:
        """Append streamed text to the open assistant entry, creating it if needed."""
        entries = list(self._vm.conversation)
        if self._streaming_id is None:
            entry = ConversationEntry(
                id=uuid.uuid4().hex[:8],
                speaker=Speaker.BOB,
                kind=EntryKind.MESSAGE,
                text=event.text,
                streaming=True,
            )
            self._streaming_id = entry.id
            entries.append(entry)
        else:
            for i, entry in enumerate(entries):
                if entry.id == self._streaming_id:
                    entries[i] = entry.with_text(entry.text + event.text)
                    break
        self._vm = replace(self._vm, conversation=tuple(entries[-MAX_CONVERSATION:]))

    def _on_response(self, event: ResponseReady) -> None:
        """Final text wins over whatever the stream assembled."""
        entries = list(self._vm.conversation)
        if self._streaming_id is not None:
            for i, entry in enumerate(entries):
                if entry.id == self._streaming_id:
                    entries[i] = entry.with_text(event.text, streaming=False)
                    break
            self._streaming_id = None
            self._vm = replace(self._vm, conversation=tuple(entries))
        else:
            self._append(
                ConversationEntry(
                    id=uuid.uuid4().hex[:8],
                    speaker=Speaker.BOB,
                    kind=EntryKind.MESSAGE,
                    text=event.text,
                )
            )

    def _on_tool_started(self, event: ToolExecutionStarted) -> None:
        entry = ConversationEntry(
            id=uuid.uuid4().hex[:8],
            speaker=Speaker.SYSTEM,
            kind=EntryKind.TOOL,
            tool_name=event.tool,
            text=event.tool,
        )
        self._tool_entries[event.call_id] = entry.id
        self._append(entry)
        self._vm = replace(
            self._vm,
            task=TaskInfo(title=event.tool, detail=f"risk: {event.risk}", active=True),
        )

    def _on_tool_finished(self, event: ToolExecutionFinished) -> None:
        entry_id = self._tool_entries.pop(event.call_id, None)
        if entry_id is not None:
            entries = list(self._vm.conversation)
            for i, entry in enumerate(entries):
                if entry.id == entry_id:
                    entries[i] = replace(
                        entry,
                        tool_ok=event.ok,
                        tool_detail=event.summary,
                        duration_ms=event.duration_ms,
                    )
                    break
            self._vm = replace(self._vm, conversation=tuple(entries))

        record = ActionRecord(
            id=event.call_id or uuid.uuid4().hex[:8],
            tool=event.tool,
            ok=event.ok,
            duration_ms=event.duration_ms,
        )
        actions = (record, *self._vm.actions)[:MAX_ACTIONS]
        self._vm = replace(self._vm, actions=actions, task=TaskInfo())

    def _on_confirmation(self, event: ConfirmationRequested) -> None:
        pending = PendingConfirmation(
            call_id=event.id,
            tool=event.tool,
            risk=event.risk,
            summary=event.summary,
        )
        self._vm = replace(self._vm, confirmation=pending)

    def _on_error(self, event: ErrorOccurred) -> None:
        self._vm = replace(self._vm, error=f"{event.component}: {event.message}")
        self._append(
            ConversationEntry(
                id=uuid.uuid4().hex[:8],
                speaker=Speaker.SYSTEM,
                kind=EntryKind.ERROR,
                text=event.message,
            )
        )

    def _on_lifecycle(self, event: Event) -> None:
        if event.type is EventType.KERNEL_READY:
            self._vm = replace(self._vm, connected=True)
        elif event.type is EventType.KERNEL_STOPPING:
            self._vm = replace(self._vm, connected=False)

    # -- direct setters used by the shell, not by events -----------------

    def set_system(self, stats: SystemStats) -> None:
        self._emit(replace(self._vm, system=stats))

    def set_providers(self, providers: ProviderInfo) -> None:
        self._emit(replace(self._vm, providers=providers))

    def set_demo_running(self, running: bool) -> None:
        self._emit(replace(self._vm, demo_running=running))

    def resolve_confirmation(self) -> None:
        self._emit(replace(self._vm, confirmation=None))

    def note(self, text: str) -> None:
        """Add a system note to the stream (used by the demo scenario)."""
        self._append(
            ConversationEntry(
                id=uuid.uuid4().hex[:8],
                speaker=Speaker.SYSTEM,
                kind=EntryKind.NOTE,
                text=text,
            )
        )
        self._notify()

    def clear_conversation(self) -> None:
        self._streaming_id = None
        self._tool_entries.clear()
        self._emit(replace(self._vm, conversation=(), actions=()))

    # -- helpers ---------------------------------------------------------

    def _append(self, entry: ConversationEntry) -> None:
        entries = (*self._vm.conversation, entry)[-MAX_CONVERSATION:]
        self._vm = replace(self._vm, conversation=entries)

    def _finish_streaming(self) -> None:
        if self._streaming_id is None:
            return
        entries = list(self._vm.conversation)
        for i, entry in enumerate(entries):
            if entry.id == self._streaming_id:
                entries[i] = replace(entry, streaming=False)
                break
        self._streaming_id = None
        self._vm = replace(self._vm, conversation=tuple(entries))

    def _emit(self, vm: ShellViewModel) -> None:
        if vm != self._vm:
            self._vm = vm
            self._notify()

    def _notify(self) -> None:
        if self._listener is not None:
            self._listener(self._vm)
