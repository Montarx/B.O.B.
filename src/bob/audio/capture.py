"""PortAudio capture, via ``sounddevice``.

The only module in B.O.B. that talks to a microphone. It is deliberately thin:
open a stream, convert each block to 16-bit mono at 16 kHz, hand it to a
callback, and get out of the way.

**What the audio callback may do.** PortAudio's callback runs on a soft-realtime
thread. Blocking it — on a lock, on an allocation storm, on inference — produces
audible glitches and, on Windows, can kill the stream outright. So the callback
here does exactly three things: downmix to mono, resample if required, and push
into a bounded queue that drops rather than blocks. VAD and STT happen elsewhere.

``sounddevice`` is imported lazily so that ``bob.audio`` can be imported, and
most of it tested, on a machine with no PortAudio at all.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from bob.audio.devices import AudioDevice, AudioDeviceError
from bob.audio.frames import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_log = logging.getLogger("bob.app.audio.capture")

#: Host APIs we prefer PortAudio to use, matched as substrings of its names.
_PREFERRED_HOST_APIS = ("wasapi", "wdm-ks", "directsound", "alsa", "pulse", "coreaudio")


def _import_sounddevice() -> Any:
    try:
        import sounddevice
    except OSError as exc:
        # The wheel ships PortAudio, so this usually means a Linux box without
        # libportaudio2 rather than a broken install.
        raise AudioDeviceError(
            "PortAudio is not available. On Linux install libportaudio2; "
            f"on Windows reinstall the sounddevice wheel. ({exc})"
        ) from exc
    except ImportError as exc:
        raise AudioDeviceError(
            'audio capture needs the voice extra: pip install -e ".[voice]"'
        ) from exc
    return sounddevice


class SoundDeviceStream:
    """A live capture stream."""

    def __init__(self, stream: Any, device: AudioDevice | None) -> None:
        self._stream = stream
        self._device = device
        self._closed = False

    @property
    def active(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._stream.active)
        except Exception:  # the device vanished under us
            return False

    @property
    def device(self) -> AudioDevice | None:
        return self._device

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stream.stop()
        except Exception:
            _log.debug("error stopping audio stream", exc_info=True)
        try:
            self._stream.close()
        except Exception:
            _log.debug("error closing audio stream", exc_info=True)


class SoundDeviceBackend:
    """:class:`~bob.audio.devices.AudioBackend` backed by PortAudio."""

    def __init__(self) -> None:
        self._sd: Any | None = None

    def _api(self) -> Any:
        if self._sd is None:
            self._sd = _import_sounddevice()
        return self._sd

    @property
    def available(self) -> bool:
        try:
            self._api()
        except AudioDeviceError:
            return False
        return True

    # -- enumeration -----------------------------------------------------

    def list_input_devices(self) -> list[AudioDevice]:
        sd = self._api()
        try:
            raw_devices = sd.query_devices()
            host_apis = sd.query_hostapis()
            default_input = sd.default.device[0]
        except Exception as exc:
            raise AudioDeviceError(f"could not enumerate audio devices: {exc}") from exc

        devices: list[AudioDevice] = []
        for index, info in enumerate(raw_devices):
            channels = int(info.get("max_input_channels", 0))
            if channels <= 0:
                continue
            api_index = int(info.get("hostapi", -1))
            api_name = ""
            if 0 <= api_index < len(host_apis):
                api_name = str(host_apis[api_index].get("name", ""))
            devices.append(
                AudioDevice(
                    index=index,
                    name=str(info.get("name", f"device {index}")).strip(),
                    channels=channels,
                    default_sample_rate=float(info.get("default_samplerate", 0.0)),
                    host_api=api_name,
                    is_default=(index == default_input),
                )
            )
        return devices

    # -- streaming -------------------------------------------------------

    def open_stream(
        self,
        device: AudioDevice | None,
        *,
        sample_rate: int = SAMPLE_RATE,
        frame_samples: int = 512,
        callback: Callable[[bytes, float], None],
    ) -> SoundDeviceStream:
        """Open a capture stream delivering 16 kHz mono int16 frames.

        Raises :class:`AudioDeviceError` with an actionable message rather than
        letting a PortAudio exception escape.
        """
        sd = self._api()
        import numpy as np

        # Ask the device for its own rate when 16 kHz is not supported natively;
        # PortAudio will resample for us where the host API can, and we resample
        # ourselves when it cannot.
        device_rate = sample_rate
        block = frame_samples
        if device is not None and device.default_sample_rate:
            native = int(device.default_sample_rate)
            if native and native != sample_rate:
                try:
                    sd.check_input_settings(device=device.index, samplerate=sample_rate, channels=1)
                except Exception:
                    device_rate = native
                    block = round(frame_samples * native / sample_rate)
                    _log.info(
                        "device %s does not accept %d Hz; capturing at %d Hz and resampling",
                        device.name,
                        sample_rate,
                        native,
                    )

        ratio = sample_rate / device_rate if device_rate else 1.0

        def _on_block(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            # Runs on PortAudio's realtime thread. Keep it short and allocation-light.
            if status:
                # Overflow means we are not draining fast enough; it is logged
                # but must not raise, or PortAudio tears the stream down.
                _log.debug("audio callback status: %s", status)
            try:
                mono = indata[:, 0] if indata.ndim > 1 else indata
                if ratio != 1.0:
                    target = max(1, round(len(mono) * ratio))
                    # Linear resample. Adequate for 16 kHz speech; a polyphase
                    # filter would be better but is not worth the cost here.
                    positions = np.linspace(0, len(mono) - 1, target)
                    mono = np.interp(positions, np.arange(len(mono)), mono.astype(np.float32))
                pcm = np.clip(mono, -32768, 32767).astype(np.int16).tobytes()
                callback(pcm, time.monotonic())
            except Exception:
                # An exception escaping here kills the stream, so swallow and log.
                _log.exception("audio callback failed")

        try:
            stream = sd.InputStream(
                device=device.index if device else None,
                samplerate=device_rate,
                channels=1,
                dtype="int16",
                blocksize=block,
                callback=_on_block,
                latency="low",
            )
            stream.start()
        except Exception as exc:
            raise AudioDeviceError(_explain_open_failure(device, exc)) from exc

        _log.info(
            "microphone open: %s at %d Hz (%d-sample blocks)",
            device.label if device else "system default",
            device_rate,
            block,
        )
        return SoundDeviceStream(stream, device)


def _explain_open_failure(device: AudioDevice | None, exc: Exception) -> str:
    """Turn a PortAudio error into something a user can act on."""
    name = device.label if device else "the default microphone"
    text = str(exc).lower()
    if "permission" in text or "access" in text or "denied" in text:
        return (
            f"Windows refused access to {name}. Check "
            "Settings > Privacy & security > Microphone and allow desktop apps."
        )
    if "unavailable" in text or "busy" in text or "in use" in text:
        return (
            f"{name} is in use by another application, possibly in exclusive mode. "
            "Close the other app and try again."
        )
    if "invalid" in text and "device" in text:
        return f"{name} disappeared. Reconnect it or pick another microphone."
    return f"could not open {name}: {exc}"


def frame_samples_for(sample_rate: int, frame_ms: float) -> int:
    """Samples per frame, rounded to something PortAudio is happy with."""
    return max(1, round(sample_rate * frame_ms / 1000.0))


__all__ = [
    "CHANNELS",
    "SAMPLE_RATE",
    "SAMPLE_WIDTH",
    "SoundDeviceBackend",
    "SoundDeviceStream",
    "frame_samples_for",
]
