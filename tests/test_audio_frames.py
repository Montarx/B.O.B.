"""Frame types, bounded queues and pre-roll."""

from __future__ import annotations

import threading

import pytest

from bob.audio.frames import (
    SAMPLE_RATE,
    AudioFrame,
    FrameQueue,
    PreRollBuffer,
    Utterance,
    join_frames,
    peak_level,
    rms_level,
    split_pcm,
)

from .audio_fixtures import FRAME_SAMPLES, frames_from, silence, tone

# -- levels -----------------------------------------------------------------


def test_silence_has_no_level() -> None:
    assert rms_level(silence()) == 0.0
    assert peak_level(silence()) == 0.0


def test_tone_registers_a_level() -> None:
    assert rms_level(tone(amplitude=0.5)) > 0.3


def test_levels_are_normalised_to_unit_range() -> None:
    loud = tone(amplitude=1.0)
    assert 0.0 <= rms_level(loud) <= 1.0
    assert 0.0 <= peak_level(loud) <= 1.0


def test_level_of_a_truncated_buffer_does_not_crash() -> None:
    """A partial sample at the end must not raise — audio arrives ragged."""
    assert rms_level(b"\x01") == 0.0
    assert rms_level(tone()[:-1]) > 0.0


def test_empty_pcm_is_silent() -> None:
    assert rms_level(b"") == 0.0
    assert peak_level(b"") == 0.0


# -- frames -----------------------------------------------------------------


def test_frame_reports_its_duration() -> None:
    frame = AudioFrame(pcm=silence(FRAME_SAMPLES), sample_rate=SAMPLE_RATE)
    assert frame.sample_count == FRAME_SAMPLES
    assert frame.duration_s == pytest.approx(0.032, abs=1e-4)


def test_split_pcm_produces_sequenced_frames() -> None:
    pcm = tone(FRAME_SAMPLES * 4)
    frames = list(split_pcm(pcm, FRAME_SAMPLES))
    assert len(frames) == 4
    assert [f.sequence for f in frames] == [0, 1, 2, 3]
    assert join_frames(frames) == pcm


def test_split_pcm_drops_a_ragged_tail() -> None:
    frames = list(split_pcm(tone(FRAME_SAMPLES) + b"\x00\x00" * 10, FRAME_SAMPLES))
    assert len(frames) == 1


# -- pre-roll ---------------------------------------------------------------


def test_pre_roll_keeps_only_the_most_recent_frames() -> None:
    buffer = PreRollBuffer(3)
    for frame in frames_from([silence()] * 6):
        buffer.push(frame)
    assert [f.sequence for f in buffer.peek()] == [3, 4, 5]


def test_pre_roll_drain_empties_it() -> None:
    buffer = PreRollBuffer(3)
    for frame in frames_from([silence()] * 3):
        buffer.push(frame)
    assert len(buffer.drain()) == 3
    assert buffer.peek() == []


def test_zero_capacity_pre_roll_keeps_nothing() -> None:
    """pre_roll_ms = 0 must genuinely disable it, not keep one frame."""
    buffer = PreRollBuffer(0)
    for frame in frames_from([silence()] * 4):
        buffer.push(frame)
    assert len(buffer) == 0
    assert buffer.drain() == []
    assert buffer.duration_s == 0.0


def test_pre_roll_reports_its_duration() -> None:
    buffer = PreRollBuffer(4)
    for frame in frames_from([silence()] * 4):
        buffer.push(frame)
    assert buffer.duration_s == pytest.approx(4 * 0.032, abs=1e-3)


# -- bounded queue ----------------------------------------------------------


def test_queue_rejects_a_nonsense_capacity() -> None:
    with pytest.raises(ValueError):
        FrameQueue(0)


def test_queue_drops_the_oldest_frame_when_full() -> None:
    """Backpressure policy: never block the audio callback."""
    queue = FrameQueue(3)
    for frame in frames_from([silence()] * 5):
        queue.push(frame)
    assert len(queue) == 3
    assert queue.stats.dropped == 2
    assert [f.sequence for f in queue.drain()] == [2, 3, 4]


def test_queue_push_reports_whether_it_dropped() -> None:
    queue = FrameQueue(2)
    frames = frames_from([silence()] * 3)
    assert queue.push(frames[0]) is True
    assert queue.push(frames[1]) is True
    assert queue.push(frames[2]) is False


def test_queue_tracks_high_water_and_drop_ratio() -> None:
    queue = FrameQueue(2)
    for frame in frames_from([silence()] * 4):
        queue.push(frame)
    assert queue.stats.high_water == 2
    assert queue.stats.drop_ratio == pytest.approx(0.5)


def test_queue_pop_returns_frames_in_order() -> None:
    queue = FrameQueue(4)
    for frame in frames_from([silence()] * 3):
        queue.push(frame)
    assert [queue.pop().sequence for _ in range(3)] == [0, 1, 2]  # type: ignore[union-attr]


def test_queue_pop_times_out_when_empty() -> None:
    assert FrameQueue(2).pop(timeout=0.01) is None


def test_closing_the_queue_wakes_a_waiting_consumer() -> None:
    """A blocked worker must not keep the process alive on shutdown."""
    queue = FrameQueue(2)
    result: list[object] = []

    def consume() -> None:
        result.append(queue.pop(timeout=5.0))

    worker = threading.Thread(target=consume)
    worker.start()
    queue.close()
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert result == [None]


def test_closed_queue_refuses_new_frames() -> None:
    queue = FrameQueue(2)
    queue.close()
    assert queue.push(frames_from([silence()])[0]) is False


def test_queue_is_thread_safe_under_contention() -> None:
    """Producers and consumers race constantly in the real pipeline."""
    queue = FrameQueue(64)
    produced = 500
    consumed: list[AudioFrame] = []
    stop = threading.Event()

    def produce() -> None:
        for frame in frames_from([silence()] * produced):
            queue.push(frame)
        stop.set()

    def consume() -> None:
        while not stop.is_set() or len(queue):
            frame = queue.pop(timeout=0.05)
            if frame is not None:
                consumed.append(frame)

    threads = [threading.Thread(target=produce), threading.Thread(target=consume)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert queue.stats.pushed == produced
    assert len(consumed) + queue.stats.dropped + len(queue) == produced


# -- utterance --------------------------------------------------------------


def test_utterance_duration_and_emptiness() -> None:
    utterance = Utterance(pcm=tone(SAMPLE_RATE), sample_rate=SAMPLE_RATE)
    assert utterance.duration_s == pytest.approx(1.0)
    assert not utterance.is_empty
    assert Utterance(pcm=b"").is_empty
