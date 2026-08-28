"""Silero VAD via ONNX Runtime.

Chosen over ``webrtcvad`` because WebRTC's VAD is famously trigger-happy on
desktop audio — fans, keyboards, music and room tone all set it off, which in a
voice assistant means constantly waking up for nothing.

Run through **onnxruntime rather than torch** deliberately: the model is about
1.8 MB, and pulling in PyTorch to run it would add well over a gigabyte. ONNX
Runtime is also what openWakeWord needs in Phase 5, so the dependency is shared
rather than additional.

The model is an LSTM, so it carries state between frames. That state must be
reset between utterances, otherwise the tail of one utterance biases the start of
the next. It expects exactly 512 samples at 16 kHz (32 ms).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bob.audio.frames import rms_level
from bob.core.errors import ProviderError
from bob.providers.base import AudioChunk, VADDecision
from bob.providers.registry import registry
from bob.utils import paths

_log = logging.getLogger("bob.app.audio.vad")

#: Silero's fixed contract at 16 kHz.
REQUIRED_SAMPLES = 512
REQUIRED_RATE = 16_000

#: Where the model is expected. Downloaded by ``python -m bob fetch-models``.
MODEL_FILENAME = "silero_vad.onnx"
MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"


def model_path() -> Path:
    return paths.models_dir() / "vad" / MODEL_FILENAME


class SileroVAD:
    """Neural VAD. Roughly 0.3-0.7 ms per 32 ms frame on a modern CPU core."""

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        model: Path | None = None,
        intra_threads: int = 1,
    ) -> None:
        self._threshold = threshold
        self._model_path = model or model_path()
        self._intra_threads = intra_threads
        self._session: Any | None = None
        self._state: Any | None = None
        self._np: Any | None = None
        self._pending = b""

    @property
    def name(self) -> str:
        return "silero-vad"

    @property
    def loaded(self) -> bool:
        return self._session is not None

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        """Load the ONNX session. Cheap — a couple of milliseconds."""
        if self._session is not None:
            return
        try:
            import numpy
            import onnxruntime
        except ImportError as exc:
            raise ProviderError(
                'Silero VAD needs the voice extra: pip install -e ".[voice]"'
            ) from exc

        if not self._model_path.is_file():
            raise ProviderError(
                f"Silero VAD model not found at {self._model_path}. Run: python -m bob fetch-models"
            )

        options = onnxruntime.SessionOptions()
        # One thread: this runs per audio frame and must not fight the STT
        # model or the UI for cores.
        options.intra_op_num_threads = self._intra_threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        try:
            self._session = onnxruntime.InferenceSession(
                str(self._model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            raise ProviderError(f"could not load Silero VAD: {exc}") from exc

        self._np = numpy
        self.reset()
        _log.info("Silero VAD loaded from %s", self._model_path)

    async def aclose(self) -> None:
        self._session = None
        self._state = None

    def reset(self) -> None:
        """Clear the LSTM state. Must happen between utterances."""
        if self._np is not None:
            self._state = self._np.zeros((2, 1, 128), dtype=self._np.float32)
        self._pending = b""

    # -- inference -------------------------------------------------------

    def process(self, frame: AudioChunk) -> VADDecision:
        """Classify one frame.

        Silero requires exactly 512 samples. Frames of a different size are
        buffered rather than rejected, so the pipeline's frame size stays a
        configuration choice instead of being dictated by the model.
        """
        if self._session is None or self._np is None:
            return VADDecision(is_speech=False, rms=rms_level(frame.pcm))

        np = self._np
        self._pending += frame.pcm
        needed = REQUIRED_SAMPLES * 2
        probability = 0.0
        consumed = False

        while len(self._pending) >= needed:
            block, self._pending = self._pending[:needed], self._pending[needed:]
            samples = np.frombuffer(block, dtype=np.int16).astype(np.float32) / 32768.0
            try:
                outputs = self._session.run(
                    None,
                    {
                        "input": samples.reshape(1, -1),
                        "state": self._state,
                        "sr": np.array(REQUIRED_RATE, dtype=np.int64),
                    },
                )
            except Exception:
                _log.exception("Silero inference failed; treating frame as silence")
                return VADDecision(is_speech=False, rms=rms_level(frame.pcm))
            probability = max(probability, float(outputs[0].item()))
            self._state = outputs[1]
            consumed = True

        if not consumed:
            # Not enough audio buffered yet to make a call.
            return VADDecision(is_speech=False, rms=rms_level(frame.pcm))

        return VADDecision(is_speech=probability >= self._threshold, rms=rms_level(frame.pcm))


@registry.register("vad", "silero")
def _factory(**kwargs: Any) -> SileroVAD:
    return SileroVAD(threshold=float(kwargs.get("threshold", 0.5)))
