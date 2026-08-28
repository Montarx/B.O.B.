"""Presenter behaviour — the shell's business logic, tested without Qt."""

from __future__ import annotations

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
from bob.core.states import BobState
from bob.ui.presenter import MAX_ACTIONS, MAX_CONVERSATION, ShellPresenter
from bob.ui.viewmodel import EntryKind, ShellViewModel, Speaker, SystemStats


def to_state(presenter: ShellPresenter, state: BobState) -> None:
    presenter.handle(
        StateChanged(source="t", old=presenter.view_model.state.value, new=state.value)
    )


# -- state ------------------------------------------------------------------


def test_state_change_updates_status_and_greek_caption() -> None:
    p = ShellPresenter()
    to_state(p, BobState.LISTENING)
    assert p.view_model.state is BobState.LISTENING
    assert p.view_model.status_text == "LISTENING"
    assert p.view_model.caption == "Σε ακούω..."


def test_connected_tracks_the_state_machine() -> None:
    p = ShellPresenter()
    assert not p.view_model.connected
    to_state(p, BobState.IDLE)
    assert p.view_model.connected
    to_state(p, BobState.OFFLINE)
    assert not p.view_model.connected


def test_handle_reports_whether_anything_changed() -> None:
    p = ShellPresenter()
    assert p.handle(StateChanged(source="t", old="OFFLINE", new="STARTING")) is True
    assert p.handle(StateChanged(source="t", old="STARTING", new="STARTING")) is False


def test_listener_is_notified_only_on_change() -> None:
    seen: list[ShellViewModel] = []
    p = ShellPresenter(on_change=seen.append)
    to_state(p, BobState.IDLE)
    assert len(seen) == 1
    p.handle(StateChanged(source="t", old="IDLE", new="IDLE"))
    assert len(seen) == 1


def test_input_is_disabled_while_thinking() -> None:
    p = ShellPresenter()
    to_state(p, BobState.IDLE)
    assert p.view_model.input_enabled
    to_state(p, BobState.THINKING)
    assert not p.view_model.input_enabled


# -- conversation -----------------------------------------------------------


def test_transcript_becomes_a_user_entry() -> None:
    p = ShellPresenter()
    p.handle(TranscriptReady(source="t", text="άνοιξε spotify"))
    entry = p.view_model.conversation[-1]
    assert entry.speaker is Speaker.USER
    assert entry.text == "άνοιξε spotify"


def test_blank_transcript_is_ignored() -> None:
    p = ShellPresenter()
    p.handle(TranscriptReady(source="t", text="   "))
    assert p.view_model.conversation == ()


def test_streamed_chunks_accumulate_into_one_entry() -> None:
    p = ShellPresenter()
    for word in ("Ναι ", "ρε, ", "έγινε."):
        p.handle(ResponseChunk(source="t", text=word))
    assert len(p.view_model.conversation) == 1
    entry = p.view_model.conversation[0]
    assert entry.text == "Ναι ρε, έγινε."
    assert entry.streaming


def test_final_response_closes_the_stream() -> None:
    p = ShellPresenter()
    p.handle(ResponseChunk(source="t", text="Ναι "))
    p.handle(ResponseReady(source="t", text="Ναι ρε, έγινε."))
    entry = p.view_model.conversation[-1]
    assert entry.text == "Ναι ρε, έγινε."
    assert not entry.streaming


def test_response_without_a_stream_still_appears() -> None:
    p = ShellPresenter()
    p.handle(ResponseReady(source="t", text="Έγινε."))
    assert p.view_model.conversation[-1].text == "Έγινε."


def test_returning_to_idle_closes_an_abandoned_stream() -> None:
    """An interrupted reply must not leave a caret blinking forever."""
    p = ShellPresenter()
    p.handle(ResponseChunk(source="t", text="μισό..."))
    to_state(p, BobState.IDLE)
    assert not p.view_model.conversation[-1].streaming


def test_two_replies_do_not_merge() -> None:
    p = ShellPresenter()
    p.handle(ResponseChunk(source="t", text="πρώτο"))
    p.handle(ResponseReady(source="t", text="πρώτο"))
    p.handle(ResponseChunk(source="t", text="δεύτερο"))
    assert len(p.view_model.conversation) == 2


def test_conversation_is_capped() -> None:
    p = ShellPresenter()
    for i in range(MAX_CONVERSATION + 30):
        p.handle(TranscriptReady(source="t", text=f"μήνυμα {i}"))
    assert len(p.view_model.conversation) == MAX_CONVERSATION
    assert p.view_model.conversation[-1].text.endswith(str(MAX_CONVERSATION + 29))


# -- tools ------------------------------------------------------------------


def test_tool_start_creates_an_entry_and_a_task() -> None:
    p = ShellPresenter()
    p.handle(ToolExecutionStarted(source="t", tool="app.open", call_id="c1", risk="low"))
    entry = p.view_model.conversation[-1]
    assert entry.kind is EntryKind.TOOL
    assert entry.tool_name == "app.open"
    assert p.view_model.task.active
    assert p.view_model.task.title == "app.open"


def test_tool_finish_updates_the_same_entry() -> None:
    p = ShellPresenter()
    p.handle(ToolExecutionStarted(source="t", tool="app.open", call_id="c1", risk="low"))
    p.handle(
        ToolExecutionFinished(
            source="t",
            tool="app.open",
            call_id="c1",
            ok=True,
            duration_ms=42.0,
            summary="Spotify",
        )
    )
    assert len(p.view_model.conversation) == 1
    entry = p.view_model.conversation[0]
    assert entry.tool_ok is True
    assert entry.tool_detail == "Spotify"
    assert not p.view_model.task.active


def test_finished_tool_is_recorded_in_activity_newest_first() -> None:
    p = ShellPresenter()
    for i, tool in enumerate(("first.tool", "second.tool")):
        p.handle(
            ToolExecutionFinished(source="t", tool=tool, call_id=f"c{i}", ok=True, duration_ms=1.0)
        )
    assert [a.tool for a in p.view_model.actions] == ["second.tool", "first.tool"]


def test_failed_tool_is_recorded_as_failed() -> None:
    p = ShellPresenter()
    p.handle(
        ToolExecutionFinished(
            source="t", tool="file.delete", call_id="c1", ok=False, duration_ms=3.0
        )
    )
    assert p.view_model.actions[0].ok is False


def test_activity_list_is_capped() -> None:
    p = ShellPresenter()
    for i in range(MAX_ACTIONS + 10):
        p.handle(
            ToolExecutionFinished(
                source="t", tool=f"t{i}", call_id=f"c{i}", ok=True, duration_ms=1.0
            )
        )
    assert len(p.view_model.actions) == MAX_ACTIONS


def test_interleaved_tool_calls_update_the_right_entries() -> None:
    """Two tools in flight at once must not overwrite each other."""
    p = ShellPresenter()
    p.handle(ToolExecutionStarted(source="t", tool="a", call_id="c1", risk="low"))
    p.handle(ToolExecutionStarted(source="t", tool="b", call_id="c2", risk="low"))
    p.handle(
        ToolExecutionFinished(
            source="t", tool="b", call_id="c2", ok=True, duration_ms=2.0, summary="B"
        )
    )
    by_tool = {e.tool_name: e for e in p.view_model.conversation}
    assert by_tool["b"].tool_detail == "B"
    assert by_tool["a"].tool_ok is None


# -- errors and confirmations -----------------------------------------------


def test_error_populates_banner_and_stream() -> None:
    p = ShellPresenter()
    p.handle(ErrorOccurred(source="t", component="stt", message="δεν βρέθηκε μικρόφωνο"))
    assert "δεν βρέθηκε μικρόφωνο" in p.view_model.error
    assert p.view_model.conversation[-1].kind is EntryKind.ERROR


def test_confirmation_request_surfaces_the_risk() -> None:
    p = ShellPresenter()
    p.handle(ConfirmationRequested(source="t", tool="file.delete", risk="high", summary="Διαγραφή"))
    pending = p.view_model.confirmation
    assert pending is not None
    assert pending.tool == "file.delete"
    assert pending.risk == "high"


def test_resolving_a_confirmation_clears_it() -> None:
    p = ShellPresenter()
    p.handle(ConfirmationRequested(source="t", tool="x", risk="high", summary="s"))
    p.resolve_confirmation()
    assert p.view_model.confirmation is None


# -- direct setters ---------------------------------------------------------


def test_system_stats_are_settable_and_deduplicated() -> None:
    seen: list[ShellViewModel] = []
    p = ShellPresenter(on_change=seen.append)
    stats = SystemStats(cpu_percent=42.0)
    p.set_system(stats)
    p.set_system(stats)
    assert p.view_model.system.cpu_percent == 42.0
    assert len(seen) == 1


def test_kernel_ready_marks_connected() -> None:
    p = ShellPresenter()
    p.handle(Event(type=EventType.KERNEL_READY, source="kernel"))
    assert p.view_model.connected


def test_clear_conversation_resets_stream_state() -> None:
    p = ShellPresenter()
    p.handle(ResponseChunk(source="t", text="μισό"))
    p.clear_conversation()
    assert p.view_model.conversation == ()
    p.handle(ResponseChunk(source="t", text="νέο"))
    assert len(p.view_model.conversation) == 1
