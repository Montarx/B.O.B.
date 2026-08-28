"""Audio frame types and bounded buffering.

Pure data structures with no I/O, no Qt and no hardware. The rules they exist to
enforce:

* the microphone callback allocates as little as possible and **never blocks**;
* memory is explicitly bounded — there is no buffer here that can grow without
  limit, because an unbounded audio buffer is a slow out-of-memory bug;
* audio is 16-bit signed mono PCM everywhere inside B.O.B., so no component has
  to ask what format it is holding.
"""

from __future__ import annotations

import array
import math
import threading
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

#: B.O.B.'s internal audio format. Whisper and Silero both want 16 kHz mono.
SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2  # bytes; int16
CHANNELS = 1

#: Full-scale value for int16, used to normalise levels to 0..1.
INT16_MAX = 32_768.0


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One fixed-size block of 16-bit mono PCM.

    Frames are immutable and cheap to pass between threads. ``sequence`` lets a
    consumer detect frames dropped under backpressure rather than silently
    transcribing audio with holes in it.
    """

    pcm: bytes
    sample_rate: int = SAMPLE_RATE
    sequence: int = 0
    #: Monotonic timestamp taken when the frame was captured.
    timestamp: float = 0.0

    @property
    def sample_count(self) -> int:
        return len(self.pcm) // SAMPLE_WIDTH

    @property
    def duration_s(self) -> float:
        return self.sample_count / self.sample_rate if self.sample_rate else 0.0

    def samples(self) -> array.array[int]:
        """Decode to signed 16-bit samples."""
        out = array.array("h")
        usable = len(self.pcm) - (len(self.pcm) % SAMPLE_WIDTH)
        out.frombytes(self.pcm[:usable])
        return out


def rms_level(pcm: bytes) -> float:
    """Root-mean-square amplitude of int16 PCM, normalised to 0..1.

    Implemented on :mod:`array` rather than ``audioop``, which was removed in
    Python 3.13, and without numpy so the pure layer stays dependency-free.
    """
    if len(pcm) < SAMPLE_WIDTH:
        return 0.0
    samples = array.array("h")
    usable = len(pcm) - (len(pcm) % SAMPLE_WIDTH)
    samples.frombytes(pcm[:usable])
    if not samples:
        return 0.0
    total = 0.0
    for sample in samples:
        total += float(sample) * float(sample)
    return min(1.0, math.sqrt(total / len(samples)) / INT16_MAX)


def peak_level(pcm: bytes) -> float:
    """Peak amplitude, normalised to 0..1. Used to detect a dead microphone."""
    if len(pcm) < SAMPLE_WIDTH:
        return 0.0
    samples = array.array("h")
    usable = len(pcm) - (len(pcm) % SAMPLE_WIDTH)
    samples.frombytes(pcm[:usable])
    if not samples:
        return 0.0
    return min(1.0, max(abs(int(s)) for s in samples) / INT16_MAX)


@dataclass(frozen=True, slots=True)
class Utterance:
    """A complete segment of speech, ready for transcription."""

    pcm: bytes
    sample_rate: int = SAMPLE_RATE
    #: Seconds of pre-roll prepended so the first syllable is not clipped.
    pre_roll_s: float = 0.0
    #: True when the segmenter cut this off at ``max_utterance_s``.
    truncated: bool = False
    #: Frames the capture layer had to drop while this was being recorded.
    dropped_frames: int = 0

    @property
    def duration_s(self) -> float:
        return (len(self.pcm) // SAMPLE_WIDTH) / self.sample_rate

    @property
    def is_empty(self) -> bool:
        return len(self.pcm) < SAMPLE_WIDTH


class PreRollBuffer:
    """A fixed-length ring of recent frames.

    VAD always decides slightly late — by the time it is confident there is
    speech, the first syllable has already gone past. Keeping a short history and
    prepending it to the utterance is what stops "Άνοιξε" being transcribed as
    "νοιξε". Bounded by construction: old frames fall off the back.
    """

    __slots__ = ("_capacity", "_frames")

    def __init__(self, capacity_frames: int) -> None:
        self._capacity = max(0, capacity_frames)
        self._frames: deque[AudioFrame] = deque(maxlen=self._capacity or 1)
        if self._capacity == 0:
            self._frames.clear()

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._frames) if self._capacity else 0

    def push(self, frame: AudioFrame) -> None:
        if self._capacity:
            self._frames.append(frame)

    def drain(self) -> list[AudioFrame]:
        """Take everything held and clear the buffer."""
        if not self._capacity:
            return []
        frames = list(self._frames)
        self._frames.clear()
        return frames

    def peek(self) -> list[AudioFrame]:
        return list(self._frames) if self._capacity else []

    def clear(self) -> None:
        self._frames.clear()

    @property
    def duration_s(self) -> float:
        return sum(f.duration_s for f in self._frames) if self._capacity else 0.0


@dataclass(slots=True)
class QueueStats:
    """Backpressure accounting, surfaced in logs and the UI."""

    pushed: int = 0
    popped: int = 0
    dropped: int = 0
    high_water: int = 0

    @property
    def drop_ratio(self) -> float:
        return self.dropped / self.pushed if self.pushed else 0.0


class FrameQueue:
    """Bounded, thread-safe frame queue with an explicit drop policy.

    The microphone callback is a soft-realtime context: it must never block and
    must never wait on a lock held by a slow consumer. So this queue **drops the
    oldest frame** when full rather than blocking the producer, and counts what
    it dropped. Losing 20 ms of old audio is far better than stalling the audio
    device, which on Windows produces an audible glitch and can kill the stream.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("frame queue capacity must be positive")
        self._capacity = capacity
        self._items: deque[AudioFrame] = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._closed = False
        self.stats = QueueStats()

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def push(self, frame: AudioFrame) -> bool:
        """Enqueue a frame. Returns ``False`` if an older frame had to be dropped.

        Safe to call from the audio callback: it takes an uncontended lock for a
        few microseconds and never waits.
        """
        with self._not_empty:
            if self._closed:
                return False
            dropped = False
            if len(self._items) >= self._capacity:
                self._items.popleft()
                self.stats.dropped += 1
                dropped = True
            self._items.append(frame)
            self.stats.pushed += 1
            self.stats.high_water = max(self.stats.high_water, len(self._items))
            self._not_empty.notify()
            return not dropped

    def pop(self, timeout: float | None = None) -> AudioFrame | None:
        """Wait for a frame. Returns ``None`` on timeout or when closed."""
        with self._not_empty:
            if not self._items and not self._closed:
                self._not_empty.wait(timeout)
            if self._items:
                self.stats.popped += 1
                return self._items.popleft()
            return None

    def drain(self) -> list[AudioFrame]:
        with self._lock:
            frames = list(self._items)
            self._items.clear()
            self.stats.popped += len(frames)
            return frames

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def close(self) -> None:
        """Wake any waiting consumer so it can shut down."""
        with self._not_empty:
            self._closed = True
            self._not_empty.notify_all()

    def reopen(self) -> None:
        """Reuse this queue for another listening session.

        Deliberately keeps :attr:`stats`: drop counts are diagnostics for the
        whole session, and silently zeroing them each time the microphone closes
        would hide exactly the backpressure problem they exist to reveal.
        """
        with self._not_empty:
            self._items.clear()
            self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed


def join_frames(frames: Iterable[AudioFrame]) -> bytes:
    """Concatenate frame payloads into one PCM buffer."""
    return b"".join(frame.pcm for frame in frames)


def split_pcm(
    pcm: bytes, frame_samples: int, *, sample_rate: int = SAMPLE_RATE
) -> Iterator[AudioFrame]:
    """Chop a PCM buffer into fixed-size frames.

    Used by tests and the benchmark harness to replay a recording through the
    same code path live audio takes.
    """
    step = frame_samples * SAMPLE_WIDTH
    if step <= 0:
        raise ValueError("frame_samples must be positive")
    for index, start in enumerate(range(0, len(pcm) - step + 1, step)):
        yield AudioFrame(
            pcm=pcm[start : start + step],
            sample_rate=sample_rate,
            sequence=index,
            timestamp=index * frame_samples / sample_rate,
        )
