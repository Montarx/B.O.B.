"""Widget-level tests.

These check *behaviour and state mapping*, never rendered pixels — a pixel test
would break on every font or antialiasing change and teach us nothing.

They run against Qt's ``offscreen`` platform, so no display is needed. The whole
module skips cleanly if PySide6 is not installed, which keeps the headless CI
path (and Phase 0's dependency-light promise) intact.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="UI tests require the [ui] extra")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from bob.core.events import StateChanged, TranscriptReady
from bob.core.states import STATUS_TEXT, BobState
from bob.ui.captions import caption_for
from bob.ui.intents import RequestState, RunDemo, SubmitText, ToggleListening
from bob.ui.responsive import layout_for_width
from bob.ui.theme.easing import ease
from bob.ui.theme.stylesheet import build_stylesheet
from bob.ui.theme.tokens import DEFAULT_THEME
from bob.ui.viewmodel import (
    ActionRecord,
    ConversationEntry,
    EntryKind,
    MicrophoneInfo,
    ShellViewModel,
    Speaker,
    SystemStats,
    TaskInfo,
)
from bob.ui.widgets.chrome import InputBar
from bob.ui.widgets.conversation import ConversationView
from bob.ui.widgets.core_view import CoreView
from bob.ui.widgets.panels import ActivityPanel, TaskPanel
from bob.ui.windows.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    app.setStyleSheet(build_stylesheet(DEFAULT_THEME))
    return app


def vm_for(state: BobState, **kwargs: object) -> ShellViewModel:
    return ShellViewModel(
        state=state,
        status_text=STATUS_TEXT[state],
        caption=caption_for(state),
        connected=state is not BobState.OFFLINE,
        **kwargs,  # type: ignore[arg-type]
    )


# -- core view --------------------------------------------------------------


def test_core_follows_the_state_machine(qt_app: QApplication) -> None:
    core = CoreView(DEFAULT_THEME)
    core.show()
    for state in BobState:
        core.set_state(state)
        assert core.state is state


def test_core_runs_slowly_when_offline(qt_app: QApplication) -> None:
    """An idle dormant core must not burn 60 fps."""
    core = CoreView(DEFAULT_THEME)
    core.show()
    assert core.fps == DEFAULT_THEME.motion.dormant_fps
    core.set_state(BobState.IDLE)
    assert core.fps == DEFAULT_THEME.motion.idle_fps


def test_core_stops_animating_when_hidden(qt_app: QApplication) -> None:
    """Frames nobody can see are pure waste."""
    core = CoreView(DEFAULT_THEME)
    core.show()
    core.set_state(BobState.THINKING)
    assert core._timer.isActive()
    core.hide()
    assert not core._timer.isActive()
    core.show()
    assert core._timer.isActive()


def test_reduced_motion_lowers_the_frame_rate(qt_app: QApplication) -> None:
    core = CoreView(DEFAULT_THEME.with_reduced_motion(True))
    core.show()
    core.set_state(BobState.THINKING)
    assert core.fps == DEFAULT_THEME.motion.reduced_motion_fps


def test_core_tick_is_safe_before_any_state_is_set(qt_app: QApplication) -> None:
    core = CoreView(DEFAULT_THEME)
    core.show()
    for _ in range(5):
        core._tick()  # must not raise


def test_core_diameter_change_resizes_every_layer(qt_app: QApplication) -> None:
    core = CoreView(DEFAULT_THEME)
    core.show()
    core.set_diameter(400)
    before = core._aperture.boundingRect().width()
    core.set_diameter(240)
    assert core._aperture.boundingRect().width() < before


def test_audio_level_is_clamped(qt_app: QApplication) -> None:
    core = CoreView(DEFAULT_THEME)
    core.set_level(4.0)
    assert core._level == 1.0
    core.set_level(-2.0)
    assert core._level == 0.0


def test_easing_curves_are_bounded() -> None:
    for name in ("Linear", "OutCubic", "InOutCubic", "OutQuint"):
        assert ease(name, 0.0) == pytest.approx(0.0, abs=1e-6)
        assert ease(name, 1.0) == pytest.approx(1.0, abs=1e-6)


# -- input bar --------------------------------------------------------------


def test_input_emits_trimmed_text(qt_app: QApplication) -> None:
    bar = InputBar(DEFAULT_THEME)
    seen: list[str] = []
    bar.submitted.connect(seen.append)
    bar._field.setText("  άνοιξε spotify  ")
    bar._submit()
    assert seen == ["άνοιξε spotify"]
    assert bar._field.text() == ""


def test_input_ignores_whitespace_only(qt_app: QApplication) -> None:
    bar = InputBar(DEFAULT_THEME)
    seen: list[str] = []
    bar.submitted.connect(seen.append)
    bar._field.setText("   ")
    bar._submit()
    assert seen == []


def test_input_can_be_disabled(qt_app: QApplication) -> None:
    bar = InputBar(DEFAULT_THEME)
    bar.set_enabled_state(False)
    assert not bar._field.isEnabled()
    bar.set_enabled_state(True)
    assert bar._field.isEnabled()


# -- conversation -----------------------------------------------------------


def test_conversation_renders_every_entry(qt_app: QApplication) -> None:
    view = ConversationView(DEFAULT_THEME)
    entries = (
        ConversationEntry(id="1", speaker=Speaker.USER, text="γεια"),
        ConversationEntry(id="2", speaker=Speaker.BOB, text="Ναι ρε"),
        ConversationEntry(
            id="3",
            speaker=Speaker.SYSTEM,
            kind=EntryKind.TOOL,
            tool_name="app.open",
            tool_ok=True,
        ),
    )
    view.set_entries(entries)
    assert view._layout.count() - 1 == len(entries)  # minus the trailing stretch


def test_conversation_skips_rebuild_when_unchanged(qt_app: QApplication) -> None:
    view = ConversationView(DEFAULT_THEME)
    entries = (ConversationEntry(id="1", speaker=Speaker.USER, text="γεια"),)
    view.set_entries(entries)
    before = view._layout.count()
    view.set_entries(entries)
    assert view._layout.count() == before


def test_streaming_entry_shows_a_caret(qt_app: QApplication) -> None:
    from bob.ui.widgets.conversation import EntryView

    entry = ConversationEntry(id="1", speaker=Speaker.BOB, text="Σκέφτομαι", streaming=True)
    assert EntryView(entry, DEFAULT_THEME)._body_text().endswith("▌")


def test_empty_conversation_shows_a_greek_hint(qt_app: QApplication) -> None:
    view = ConversationView(DEFAULT_THEME)
    view.set_entries(())
    assert view._empty.isVisibleTo(view)


# -- panels -----------------------------------------------------------------


def test_task_panel_hides_progress_when_idle(qt_app: QApplication) -> None:
    panel = TaskPanel(DEFAULT_THEME)
    panel.show()
    panel.set_task(TaskInfo(title="app.open", detail="risk: low", active=True))
    assert panel._meter.isVisibleTo(panel)
    panel.set_task(TaskInfo())
    assert not panel._meter.isVisibleTo(panel)


def test_activity_panel_caps_visible_rows(qt_app: QApplication) -> None:
    panel = ActivityPanel(DEFAULT_THEME)
    records = tuple(
        ActionRecord(id=str(i), tool=f"t{i}", ok=True, duration_ms=1.0) for i in range(30)
    )
    panel.set_actions(records)
    assert len(panel._rows) == ActivityPanel.MAX_ROWS


def test_activity_panel_shows_empty_state(qt_app: QApplication) -> None:
    panel = ActivityPanel(DEFAULT_THEME)
    panel.show()
    panel.set_actions(())
    assert panel._empty.isVisibleTo(panel)


# -- main window ------------------------------------------------------------


def test_window_renders_a_snapshot(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.resize(1600, 960)
    window.render_view_model(vm_for(BobState.LISTENING))
    assert window.core.state is BobState.LISTENING


def test_window_primes_every_panel_on_first_paint(qt_app: QApplication) -> None:
    """The first snapshot equals the default, so a pure diff would render nothing."""
    window = MainWindow(DEFAULT_THEME)
    window.show()
    assert not window._task_panel._meter.isVisibleTo(window._task_panel)


def test_window_hides_rails_on_a_small_screen(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.resize(1000, 700)
    window.show()
    assert not window._left_rail.isVisibleTo(window)
    window.resize(1920, 1080)
    assert window._left_rail.isVisibleTo(window)


def test_window_raises_a_submit_intent(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    seen: list[object] = []
    window.intentRaised.connect(seen.append)
    window._input._field.setText("άνοιξε spotify")
    window._input._submit()
    assert seen == [SubmitText("άνοιξε spotify")]


def test_window_disables_input_while_thinking(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(vm_for(BobState.IDLE))
    assert window._input._field.isEnabled()
    window.render_view_model(vm_for(BobState.THINKING))
    assert not window._input._field.isEnabled()


def test_window_shows_an_error_banner(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.show()
    window.render_view_model(vm_for(BobState.ERROR, error="stt: κάτι πήγε στραβά"))
    assert window._error.isVisibleTo(window)
    window.render_view_model(vm_for(BobState.IDLE))
    assert not window._error.isVisibleTo(window)


def test_window_renders_system_stats(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(vm_for(BobState.IDLE, system=SystemStats(cpu_percent=42.0)))
    assert "42" in window._system_panel._cpu._value.text()


# -- developer tooling ------------------------------------------------------


def test_debug_overlay_is_absent_in_production(qt_app: QApplication) -> None:
    """The state switcher must never appear in the normal interface."""
    assert MainWindow(DEFAULT_THEME).debug_overlay is None


def test_debug_overlay_exists_and_starts_hidden_in_dev(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME, dev_tools=True)
    window.show()
    overlay = window.debug_overlay
    assert overlay is not None
    assert not overlay.isVisible()
    window._toggle_debug()
    assert overlay.isVisible()


def test_debug_buttons_raise_state_intents(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME, dev_tools=True)
    overlay = window.debug_overlay
    assert overlay is not None
    seen: list[object] = []
    window.intentRaised.connect(seen.append)
    overlay._buttons[BobState.THINKING].click()
    assert seen == [RequestState(BobState.THINKING)]


def test_debug_overlay_covers_every_state(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME, dev_tools=True)
    overlay = window.debug_overlay
    assert overlay is not None
    assert set(overlay._buttons) == set(BobState)


def test_debug_demo_button_toggles(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME, dev_tools=True)
    overlay = window.debug_overlay
    assert overlay is not None
    seen: list[object] = []
    window.intentRaised.connect(seen.append)
    overlay._toggle_demo()
    assert seen == [RunDemo(True)]
    overlay.set_demo_running(True)
    overlay._toggle_demo()
    assert seen[-1] == RunDemo(False)


def test_layout_spec_matches_the_window_width(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.resize(1920, 1080)
    window.show()
    assert window._layout_spec == layout_for_width(window.width())


# --------------------------------------------------------------------------
# Phase 2: the listen control and transcript display
# --------------------------------------------------------------------------


def test_microphone_button_offers_to_listen_when_idle(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(
        vm_for(BobState.IDLE, microphone=MicrophoneInfo(available=True, device="Mic"))
    )
    assert window._microphone._button.isEnabled()
    assert "Άκου" in window._microphone._button.text()


def test_microphone_button_offers_to_stop_while_listening(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(
        vm_for(
            BobState.LISTENING,
            microphone=MicrophoneInfo(available=True, listening=True, device="Mic"),
        )
    )
    assert "Σταμάτα" in window._microphone._button.text()


def test_microphone_button_is_disabled_while_transcribing(qt_app: QApplication) -> None:
    """Requirement 8: no listening flow running in parallel with transcription."""
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(
        vm_for(BobState.TRANSCRIBING, microphone=MicrophoneInfo(available=True))
    )
    assert not window._microphone._button.isEnabled()


def test_microphone_button_reports_an_unavailable_device(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(
        vm_for(
            BobState.IDLE,
            microphone=MicrophoneInfo(available=False, error="Δεν βρέθηκε μικρόφωνο"),
        )
    )
    assert not window._microphone._button.isEnabled()
    assert "Χωρίς μικρόφωνο" in window._microphone._button.text()


def test_microphone_button_raises_a_listening_intent(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(vm_for(BobState.IDLE, microphone=MicrophoneInfo(available=True)))
    seen: list[object] = []
    window.intentRaised.connect(seen.append)
    window._microphone._button.click()
    assert seen == [ToggleListening(True)]


def test_the_stop_intent_is_raised_while_listening(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(
        vm_for(
            BobState.LISTENING,
            microphone=MicrophoneInfo(available=True, listening=True),
        )
    )
    seen: list[object] = []
    window.intentRaised.connect(seen.append)
    window._microphone._button.click()
    assert seen == [ToggleListening(False)]


def test_the_hotkey_toggles_listening(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(vm_for(BobState.IDLE, microphone=MicrophoneInfo(available=True)))
    seen: list[object] = []
    window.intentRaised.connect(seen.append)
    window._toggle_listening()
    assert seen == [ToggleListening(True)]


def test_the_hotkey_does_nothing_when_busy(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.render_view_model(vm_for(BobState.THINKING))
    seen: list[object] = []
    window.intentRaised.connect(seen.append)
    window._toggle_listening()
    assert seen == []


def test_partial_transcript_appears_and_is_replaced(qt_app: QApplication) -> None:
    window = MainWindow(DEFAULT_THEME)
    window.show()
    window.render_view_model(vm_for(BobState.TRANSCRIBING, partial_transcript="Άνοιξε το..."))
    assert window._partial.isVisibleTo(window)
    assert window._partial.text() == "Άνοιξε το..."

    window.render_view_model(vm_for(BobState.IDLE))
    assert not window._partial.isVisibleTo(window)


def test_a_transcript_reaches_the_conversation(qt_app: QApplication) -> None:
    """The acceptance criterion, at the UI layer."""
    from bob.ui.presenter import ShellPresenter

    window = MainWindow(DEFAULT_THEME)
    presenter = ShellPresenter(on_change=window.render_view_model)
    presenter.handle(StateChanged(source="t", old="OFFLINE", new="STARTING"))
    presenter.handle(StateChanged(source="t", old="STARTING", new="IDLE"))
    presenter.handle(StateChanged(source="t", old="IDLE", new="LISTENING"))
    presenter.handle(StateChanged(source="t", old="LISTENING", new="TRANSCRIBING"))
    presenter.handle(TranscriptReady(source="stt", text="Άνοιξε το Spotify"))
    presenter.handle(StateChanged(source="t", old="TRANSCRIBING", new="IDLE"))

    assert window._conversation._rendered[-1].text == "Άνοιξε το Spotify"
    assert window.core.state is BobState.IDLE


def test_microphone_level_reaches_the_core(qt_app: QApplication) -> None:
    """Requirement 12: normalised levels only, never samples."""
    window = MainWindow(DEFAULT_THEME)
    window.set_audio_level(0.62, "input")
    assert window.core._level == pytest.approx(0.62)
