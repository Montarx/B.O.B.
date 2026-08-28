"""Synthetic audio for tests.

No microphone, no model download, no recorded assets in the repository. Tests
generate the audio they need, which keeps CI fast and hermetic and means a test
failure is never "the fixture file drifted".
"""

from __future__ import annotations

import array
import math
import struct
from collections.abc import Iterable, Iterator

from bob.audio.frames import SAMPLE_RATE, AudioFrame
from bob.providers.base import VADDecision

#: 32 ms at 16 kHz — Silero's native block, and B.O.B.'s default frame.
FRAME_MS = 32.0
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)


def silence(samples: int = FRAME_SAMPLES) -> bytes:
    return b"\x00\x00" * samples


def tone(
    samples: int = FRAME_SAMPLES,
    *,
    frequency: float = 220.0,
    amplitude: float = 0.35,
    phase: float = 0.0,
) -> bytes:
    """A sine, standing in for voiced speech."""
    peak = int(amplitude * 32767)
    values = array.array(
        "h",
        (
            int(peak * math.sin(2 * math.pi * frequency * (i / SAMPLE_RATE) + phase))
            for i in range(samples)
        ),
    )
    return values.tobytes()


def noise(samples: int = FRAME_SAMPLES, *, amplitude: float = 0.01, seed: int = 7) -> bytes:
    """Low-level pseudo-random noise, standing in for room tone."""
    state = seed
    peak = int(amplitude * 32767)
    out = array.array("h")
    for _ in range(samples):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        out.append(((state % (2 * peak + 1)) - peak) if peak else 0)
    return out.tobytes()


def frames_from(payloads: Iterable[bytes], *, start: int = 0) -> list[AudioFrame]:
    """Wrap payloads as sequenced, timestamped frames."""
    return [
        AudioFrame(
            pcm=payload,
            sample_rate=SAMPLE_RATE,
            sequence=start + index,
            timestamp=(start + index) * FRAME_MS / 1000.0,
        )
        for index, payload in enumerate(payloads)
    ]


def speech_pattern(pattern: str) -> list[VADDecision]:
    """Turn a string like ``"...###..."`` into VAD decisions.

    ``#`` is speech, ``.`` is silence. This makes segmentation tests read like a
    picture of the audio, which matters when the behaviour under test is timing.
    """
    return [VADDecision(is_speech=(ch == "#"), rms=0.2 if ch == "#" else 0.0) for ch in pattern]


def frames_for_pattern(pattern: str) -> list[AudioFrame]:
    """Frames matching a speech pattern: tone where speech, noise where silence."""
    payloads = [
        tone(phase=index * 0.7) if ch == "#" else noise() for index, ch in enumerate(pattern)
    ]
    return frames_from(payloads)


def ms_to_frames(milliseconds: float) -> int:
    return round(milliseconds / FRAME_MS)


def wav_bytes(pcm: bytes, *, sample_rate: int = SAMPLE_RATE, channels: int = 1) -> bytes:
    """A minimal RIFF/WAVE container, for benchmark-loader tests."""
    byte_rate = sample_rate * channels * 2
    return b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + len(pcm)),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, channels * 2, 16),
            b"data",
            struct.pack("<I", len(pcm)),
            pcm,
        )
    )


class ScriptedBackend:
    """An :class:`~bob.audio.devices.AudioBackend` that replays canned audio.

    Lets the whole pipeline be exercised — capture callback, queue, worker
    thread, segmenter, STT — with no sound card anywhere.
    """

    def __init__(
        self,
        devices: list[object] | None = None,
        *,
        payloads: list[bytes] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        from bob.audio.devices import AudioDevice

        self._devices = (
            devices
            if devices is not None
            else [AudioDevice(0, "Test Microphone", 1, 16000.0, "TestAPI", True)]
        )
        self._payloads = payloads or []
        self._fail_with = fail_with
        self.opened = 0
        self.closed = 0
        self.last_stream: ScriptedStream | None = None

    def list_input_devices(self) -> list[object]:
        if isinstance(self._fail_with, Exception) and not self._devices:
            raise self._fail_with
        return list(self._devices)

    def open_stream(self, device, *, sample_rate, frame_samples, callback):  # type: ignore[no-untyped-def]
        if self._fail_with is not None:
            raise self._fail_with
        self.opened += 1
        stream = ScriptedStream(self, callback)
        self.last_stream = stream
        return stream


class ScriptedStream:
    """A stream whose audio is pushed by the test rather than by a device."""

    def __init__(self, backend: ScriptedBackend, callback) -> None:  # type: ignore[no-untyped-def]
        self._backend = backend
        self._callback = callback
        self._active = True
        self._clock = 0.0

    @property
    def active(self) -> bool:
        return self._active

    def feed(self, payloads: Iterable[bytes], *, frame_ms: float = FRAME_MS) -> None:
        """Deliver audio exactly as PortAudio's callback thread would."""
        for payload in payloads:
            if not self._active:
                return
            self._callback(payload, self._clock)
            self._clock += frame_ms / 1000.0

    def close(self) -> None:
        if self._active:
            self._active = False
            self._backend.closed += 1


def chunk_stream(pcm: bytes, samples: int = FRAME_SAMPLES) -> Iterator[bytes]:
    step = samples * 2
    for start in range(0, len(pcm) - step + 1, step):
        yield pcm[start : start + step]
