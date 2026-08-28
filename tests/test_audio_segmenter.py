"""Speech segmentation.

Patterns read as pictures of the audio: ``#`` is a speech frame, ``.`` is
silence, one character per 32 ms. That makes timing behaviour legible, which
matters because every bug in this file is a timing bug.
"""

from __future__ import annotations

import pytest

from bob.audio.frames import SAMPLE_WIDTH
from bob.audio.segmenter import (
    DiscardReason,
    SegmentationConfig,
    Segmenter,
    SegmentState,
    SpeechBegan,
    SpeechDiscarded,
    SpeechEnded,
    segment_all,
)

from .audio_fixtures import FRAME_MS, frames_for_pattern, ms_to_frames, speech_pattern

#: Short timings keep the patterns readable. Production defaults are longer.
FAST = SegmentationConfig(
    min_speech_ms=96,  # 3 frames
    end_silence_ms=128,  # 4 frames
    pre_roll_ms=96,  # 3 frames
    max_utterance_s=1.0,
    tail_silence_ms=64,  # 2 frames
    min_utterance_ms=64,
)


def run(pattern: str, config: SegmentationConfig = FAST) -> list[object]:
    segmenter = Segmenter(config, frame_ms=FRAME_MS)
    return segment_all(segmenter, frames_for_pattern(pattern), speech_pattern(pattern))


def only(signals: list[object], kind: type) -> list[object]:
    return [s for s in signals if isinstance(s, kind)]


def frames_in(utterance: object) -> int:
    return len(utterance.pcm) // SAMPLE_WIDTH // int(16_000 * FRAME_MS / 1000)  # type: ignore[attr-defined]


# -- the happy path ---------------------------------------------------------


def test_a_clean_utterance_begins_and_ends() -> None:
    signals = run("......########........")
    assert len(only(signals, SpeechBegan)) == 1
    assert len(only(signals, SpeechEnded)) == 1


def test_nothing_is_emitted_for_pure_silence() -> None:
    assert run("." * 40) == []


def test_speech_that_never_ends_stays_open() -> None:
    """Still talking is not the same as finished."""
    assert only(run("...." + "#" * 20), SpeechEnded) == []


def test_segmenter_returns_to_armed_after_an_utterance() -> None:
    segmenter = Segmenter(FAST, frame_ms=FRAME_MS)
    pattern = "....######......."
    segment_all(segmenter, frames_for_pattern(pattern), speech_pattern(pattern))
    assert segmenter.state is SegmentState.ARMED
    assert not segmenter.is_capturing


def test_two_utterances_are_separated() -> None:
    signals = run("...####........####........")
    assert len(only(signals, SpeechEnded)) == 2


# -- pre-roll ---------------------------------------------------------------


def test_pre_roll_is_prepended_so_the_first_syllable_survives() -> None:
    """The whole point: VAD is late, so keep what came just before it fired."""
    speech_frames = 8
    ended = only(run("......" + "#" * speech_frames + "." * 8), SpeechEnded)[0]
    utterance = ended.utterance  # type: ignore[attr-defined]

    pre_roll_frames = ms_to_frames(FAST.pre_roll_ms)
    tail_frames = ms_to_frames(FAST.tail_silence_ms)
    expected = pre_roll_frames + speech_frames + tail_frames
    assert frames_in(utterance) == expected


def test_utterance_is_longer_than_the_speech_alone() -> None:
    speech_frames = 8
    ended = only(run("......" + "#" * speech_frames + "." * 8), SpeechEnded)[0]
    speech_only_s = speech_frames * FRAME_MS / 1000
    assert ended.utterance.duration_s > speech_only_s  # type: ignore[attr-defined]


def test_zero_pre_roll_is_honoured() -> None:
    config = SegmentationConfig(
        min_speech_ms=96,
        end_silence_ms=128,
        pre_roll_ms=0,
        max_utterance_s=1.0,
        tail_silence_ms=0,
        min_utterance_ms=64,
    )
    speech_frames = 8
    ended = only(run("......" + "#" * speech_frames + "." * 8, config), SpeechEnded)[0]
    assert frames_in(ended.utterance) == speech_frames  # type: ignore[attr-defined]


def test_pre_roll_is_capped_at_its_configured_length() -> None:
    """A minute of silence beforehand must not be prepended."""
    ended = only(run("." * 60 + "#" * 8 + "." * 8), SpeechEnded)[0]
    expected = ms_to_frames(FAST.pre_roll_ms) + 8 + ms_to_frames(FAST.tail_silence_ms)
    assert frames_in(ended.utterance) == expected  # type: ignore[attr-defined]


# -- rejecting things that are not speech -----------------------------------


def test_a_brief_blip_is_discarded_not_transcribed() -> None:
    """A cough or a keyboard click must never reach the STT model."""
    signals = run("......##.........")
    assert only(signals, SpeechEnded) == []
    discarded = only(signals, SpeechDiscarded)
    assert discarded and discarded[0].reason is DiscardReason.TOO_SHORT  # type: ignore[attr-defined]


def test_a_blip_does_not_prevent_real_speech_immediately_after() -> None:
    """Candidate frames go back into the pre-roll rather than being thrown away."""
    signals = run("...##..######......")
    assert len(only(signals, SpeechEnded)) == 1


def test_min_speech_boundary_is_inclusive() -> None:
    """Exactly min_speech_ms of speech counts as speech."""
    exact = ms_to_frames(FAST.min_speech_ms)
    assert only(run("...." + "#" * exact + "." * 8), SpeechBegan)


def test_one_frame_below_the_boundary_is_rejected() -> None:
    short = ms_to_frames(FAST.min_speech_ms) - 1
    assert only(run("...." + "#" * short + "." * 8), SpeechBegan) == []


# -- pauses and endings -----------------------------------------------------


def test_a_short_pause_does_not_end_the_utterance() -> None:
    """People pause mid-sentence; cutting them off there is infuriating."""
    signals = run("...####..####.........")
    assert len(only(signals, SpeechEnded)) == 1


def test_the_pause_is_kept_inside_the_utterance() -> None:
    """Removing internal silence would distort the speech Whisper hears."""
    with_pause = only(run("...####..####........"), SpeechEnded)[0]
    without = only(run("...########........"), SpeechEnded)[0]
    assert frames_in(with_pause.utterance) > frames_in(without.utterance)  # type: ignore[attr-defined]


def test_end_silence_must_be_sustained() -> None:
    needed = ms_to_frames(FAST.end_silence_ms)
    assert only(run("...######" + "." * (needed - 1)), SpeechEnded) == []
    assert only(run("...######" + "." * needed), SpeechEnded)


def test_only_a_little_trailing_silence_is_kept() -> None:
    """Whisper does not need most of a second of nothing on the end."""
    ended = only(run("...######" + "." * 20), SpeechEnded)[0]
    kept = frames_in(ended.utterance) - ms_to_frames(FAST.pre_roll_ms) - 6  # type: ignore[attr-defined]
    assert kept == ms_to_frames(FAST.tail_silence_ms)


# -- limits -----------------------------------------------------------------


def test_endless_speech_is_cut_at_the_maximum() -> None:
    """Without this, one stuck VAD means an unbounded buffer."""
    signals = run("..." + "#" * 200)
    ended = only(signals, SpeechEnded)
    assert ended, "a very long utterance must still be emitted"
    assert ended[0].utterance.truncated is True  # type: ignore[attr-defined]


def test_a_truncated_utterance_respects_the_length_limit() -> None:
    ended = only(run("..." + "#" * 200), SpeechEnded)[0]
    assert ended.utterance.duration_s <= FAST.max_utterance_s + 0.1  # type: ignore[attr-defined]


def test_a_normal_utterance_is_not_flagged_truncated() -> None:
    ended = only(run("...######........"), SpeechEnded)[0]
    assert ended.utterance.truncated is False  # type: ignore[attr-defined]


def test_an_utterance_below_the_minimum_length_is_dropped() -> None:
    config = SegmentationConfig(
        min_speech_ms=32,
        end_silence_ms=64,
        pre_roll_ms=0,
        max_utterance_s=5.0,
        tail_silence_ms=0,
        min_utterance_ms=500,
    )
    signals = run("...##.....", config)
    assert only(signals, SpeechEnded) == []


# -- dropped frames ---------------------------------------------------------


def test_dropped_frames_are_reported_on_the_utterance() -> None:
    """If backpressure lost audio, the transcript consumer should know."""
    segmenter = Segmenter(FAST, frame_ms=FRAME_MS)
    pattern = "...######........"
    frames = frames_for_pattern(pattern)
    decisions = speech_pattern(pattern)
    signals = []
    for index, (frame, decision) in enumerate(zip(frames, decisions, strict=True)):
        if index == 5:
            segmenter.note_dropped(3)
        signal = segmenter.push(frame, decision)
        if signal:
            signals.append(signal)
    ended = only(signals, SpeechEnded)[0]
    assert ended.utterance.dropped_frames == 3  # type: ignore[attr-defined]


def test_drop_count_resets_between_utterances() -> None:
    segmenter = Segmenter(FAST, frame_ms=FRAME_MS)
    pattern = "...######........###nnn####........".replace("n", ".")
    frames = frames_for_pattern(pattern)
    decisions = speech_pattern(pattern)
    segmenter.note_dropped(2)
    results = [
        s for s in (segmenter.push(f, d) for f, d in zip(frames, decisions, strict=True)) if s
    ]
    ended = only(results, SpeechEnded)
    assert len(ended) == 2
    assert ended[1].utterance.dropped_frames == 0  # type: ignore[attr-defined]


# -- manual control ---------------------------------------------------------


def test_flush_emits_whatever_has_been_captured() -> None:
    """The user pressed stop mid-sentence; do not throw the audio away."""
    segmenter = Segmenter(FAST, frame_ms=FRAME_MS)
    pattern = "...######"
    for frame, decision in zip(frames_for_pattern(pattern), speech_pattern(pattern), strict=True):
        segmenter.push(frame, decision)
    assert segmenter.is_capturing
    result = segmenter.flush()
    assert isinstance(result, SpeechEnded)
    assert segmenter.state is SegmentState.ARMED


def test_flush_while_idle_returns_nothing() -> None:
    assert Segmenter(FAST, frame_ms=FRAME_MS).flush() is None


def test_reset_discards_in_progress_capture() -> None:
    segmenter = Segmenter(FAST, frame_ms=FRAME_MS)
    pattern = "...######"
    for frame, decision in zip(frames_for_pattern(pattern), speech_pattern(pattern), strict=True):
        segmenter.push(frame, decision)
    segmenter.reset()
    assert segmenter.state is SegmentState.ARMED
    assert segmenter.captured_frames == 0


# -- configuration ----------------------------------------------------------


def test_frames_for_ms_converts_correctly() -> None:
    assert FAST.frames_for_ms(320, 32.0) == 10
    assert FAST.frames_for_ms(0, 32.0) == 0


def test_frames_for_ms_is_safe_with_a_zero_frame_size() -> None:
    assert FAST.frames_for_ms(320, 0.0) == 0


@pytest.mark.parametrize("pre_roll_ms", [0, 96, 320, 1000])
def test_any_pre_roll_setting_still_produces_an_utterance(pre_roll_ms: int) -> None:
    config = SegmentationConfig(
        min_speech_ms=96,
        end_silence_ms=128,
        pre_roll_ms=pre_roll_ms,
        max_utterance_s=5.0,
        tail_silence_ms=32,
        min_utterance_ms=64,
    )
    assert only(run("." * 40 + "#" * 10 + "." * 10, config), SpeechEnded)
