"""Microphone enumeration and selection.

Device *logic* lives here as pure functions over a description of what is
available; actual enumeration sits behind :class:`AudioBackend` so tests never
need a sound card. Nothing in the UI touches a device directly — it asks this
module, which is the whole point of requirement "do not scatter device handling
through UI code".

Windows note: PortAudio exposes several host APIs, and its default is usually
**MME**, which carries roughly 100 ms of extra latency. B.O.B. explicitly prefers
**WASAPI**, then DirectSound, then whatever is left.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from bob.core.errors import BobError

_log = logging.getLogger("bob.app.audio.devices")

#: Host API preference, best first. Names are matched case-insensitively as
#: substrings, because PortAudio spells them differently across platforms.
HOST_API_PREFERENCE: tuple[str, ...] = (
    "wasapi",  # Windows: lowest latency, exclusive mode available
    "wdm-ks",  # Windows: kernel streaming, lower level still
    "directsound",  # Windows: acceptable fallback
    "alsa",  # Linux
    "pulse",  # Linux
    "coreaudio",  # macOS
    "mme",  # Windows: last resort, high latency
)


class AudioDeviceError(BobError):
    """The requested microphone is unavailable, gone, or refused access."""


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """One capture device, as B.O.B. sees it."""

    index: int
    name: str
    channels: int
    default_sample_rate: float
    host_api: str = ""
    is_default: bool = False

    @property
    def label(self) -> str:
        """What the user sees in the settings list."""
        suffix = f" ({self.host_api})" if self.host_api else ""
        return f"{self.name}{suffix}"

    @property
    def host_api_rank(self) -> int:
        """Lower is better. Unknown host APIs sort last."""
        lowered = self.host_api.lower()
        for rank, name in enumerate(HOST_API_PREFERENCE):
            if name in lowered:
                return rank
        return len(HOST_API_PREFERENCE)


@runtime_checkable
class AudioBackend(Protocol):
    """The seam between B.O.B. and a real sound card."""

    def list_input_devices(self) -> list[AudioDevice]: ...

    def open_stream(
        self,
        device: AudioDevice | None,
        *,
        sample_rate: int,
        frame_samples: int,
        callback: Callable[[bytes, float], None],
    ) -> StreamHandle: ...


@runtime_checkable
class StreamHandle(Protocol):
    """A running capture stream."""

    @property
    def active(self) -> bool: ...

    def close(self) -> None: ...


def select_device(devices: Sequence[AudioDevice], requested: str | None) -> AudioDevice | None:
    """Resolve a configured microphone name to an actual device.

    Matching is by *name*, never by index: PortAudio indices shift when a USB
    headset is plugged in, so a configured index would silently start recording
    from the wrong device. Falls back to the system default, then to the best
    available host API.

    Returns ``None`` when there are no input devices at all, which the caller
    reports as a proper error rather than crashing.
    """
    if not devices:
        return None

    if requested:
        wanted = requested.strip().lower()
        exact = [d for d in devices if d.name.lower() == wanted]
        if exact:
            return _best(exact)
        partial = [d for d in devices if wanted in d.name.lower()]
        if partial:
            return _best(partial)
        _log.warning(
            "configured microphone %r not found; falling back to the default",
            requested,
        )

    defaults = [d for d in devices if d.is_default]
    if defaults:
        # The system default identifies the right *physical* device, but on
        # Windows it is usually the MME entry. Keep the device, upgrade the host
        # API: pick the best-ranked entry sharing that name.
        return _best(same_named(devices, defaults[0].name) or defaults)
    return _best(devices)


def same_named(devices: Sequence[AudioDevice], name: str) -> list[AudioDevice]:
    """All entries for one physical device across host APIs."""
    wanted = name.strip().lower()
    return [d for d in devices if d.name.strip().lower() == wanted]


def _best(devices: Sequence[AudioDevice]) -> AudioDevice:
    """Prefer the lowest-latency host API, then the lowest index for stability."""
    return min(devices, key=lambda d: (d.host_api_rank, d.index))


def describe_devices(devices: Sequence[AudioDevice]) -> str:
    """A readable listing, used by ``python -m bob devices``."""
    if not devices:
        return "No input devices found."
    lines = ["Available microphones:"]
    for device in sorted(devices, key=lambda d: (d.host_api_rank, d.index)):
        marker = "*" if device.is_default else " "
        lines.append(
            f" {marker} [{device.index:>2}] {device.name}"
            f"  ({device.host_api}, {device.channels}ch, "
            f"{device.default_sample_rate / 1000:.1f} kHz)"
        )
    lines.append("\n* = system default. Set audio.input_device to a name, not an index.")
    return "\n".join(lines)
