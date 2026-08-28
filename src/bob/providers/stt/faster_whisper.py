"""faster-whisper STT provider.

CTranslate2 rather than reference Whisper: roughly 4x faster at the same
accuracy, with int8 quantisation that makes CPU operation realistic. Critically
for B.O.B., CTranslate2 **releases the GIL** during inference, so running it in a
thread genuinely parallelises instead of blocking the kernel loop.

Greek-specific choices, which are the point of this provider:

* ``language`` is pinned to ``el`` rather than auto-detected. Auto-detection on a
  two-second utterance is unreliable and will occasionally decide that Greek with
  English app names is English, producing transliterated nonsense.
* An ``initial_prompt`` seeds the decoder with the vocabulary B.O.B. actually
  hears — application names, technical English words. Whisper conditions on it,
  which measurably improves proper nouns like "Spotify" and "Visual Studio Code"
  instead of rendering them phonetically in Greek script.
* ``condition_on_previous_text`` is **off**. It is designed for long-form audio;
  on short commands it lets one bad transcript poison the next.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from bob.core.errors import ProviderError
from bob.providers.base import AudioChunk, Transcript
from bob.providers.registry import registry
from bob.utils import paths

_log = logging.getLogger("bob.ai.stt")

#: Seeds the decoder with vocabulary B.O.B. is likely to hear. Kept short —
#: Whisper only conditions on the last ~224 tokens, and a long prompt crowds out
#: the audio.
GREEK_PROMPT = (
    "Άνοιξε το Spotify, το Discord και το Visual Studio Code. "
    "Έλεγξε τη RAM, τη CPU και τον δίσκο. "
    "Πήγαινε στον φάκελο Downloads. Κάνε update το project."
)

#: Model names we know how to fetch, smallest first.
KNOWN_MODELS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "large-v3-turbo",
)


@dataclass(frozen=True, slots=True)
class WhisperConfig:
    model: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "auto"
    language: str | None = "el"
    beam_size: int = 5
    vad_filter: bool = False
    initial_prompt: str | None = GREEK_PROMPT
    #: Whisper hallucinates confidently on silence; these suppress the worst of it.
    no_speech_threshold: float = 0.6
    log_prob_threshold: float = -1.0
    temperature: tuple[float, ...] = (0.0, 0.2, 0.4)


def resolve_compute_type(device: str, requested: str) -> str:
    """Pick a sensible quantisation when the user said ``auto``.

    int8 on CPU is the difference between usable and unusable; float16 on GPU is
    the quality/speed sweet spot. ``int8_float16`` is for small GPUs where the
    weights must be squeezed but compute can stay half precision.
    """
    if requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


def resolve_device(requested: str) -> str:
    """Resolve ``auto`` to cuda when CTranslate2 can actually see a GPU."""
    if requested != "auto":
        return requested
    try:
        import ctranslate2

        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


class FasterWhisperSTT:
    """Local Whisper transcription."""

    def __init__(self, config: WhisperConfig | None = None) -> None:
        self._config = config or WhisperConfig()
        self._model: Any | None = None
        self._device = ""
        self._compute_type = ""
        self._load_seconds = 0.0

    @property
    def name(self) -> str:
        return f"faster-whisper:{self._config.model}"

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_seconds(self) -> float:
        return self._load_seconds

    @property
    def description(self) -> str:
        return f"{self._config.model} ({self._device}/{self._compute_type})"

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        """Load the model.

        Slow — seconds to minutes on a first run that has to download. The
        pipeline calls this from a worker thread, never from the GUI thread or
        the kernel loop.
        """
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ProviderError(
                'faster-whisper is not installed: pip install -e ".[voice]"'
            ) from exc

        self._device = resolve_device(self._config.device)
        self._compute_type = resolve_compute_type(self._device, self._config.compute_type)

        started = time.perf_counter()
        try:
            self._model = WhisperModel(
                self._config.model,
                device=self._device,
                compute_type=self._compute_type,
                download_root=str(paths.models_dir() / "whisper"),
            )
        except Exception as exc:
            raise ProviderError(_explain_load_failure(self._config, self._device, exc)) from exc
        self._load_seconds = time.perf_counter() - started

        _log.info(
            "whisper %s loaded on %s/%s in %.1fs",
            self._config.model,
            self._device,
            self._compute_type,
            self._load_seconds,
        )

    async def aclose(self) -> None:
        self._model = None

    # -- transcription ---------------------------------------------------

    async def transcribe(self, audio: AudioChunk, *, language: str | None = None) -> Transcript:
        """Transcribe one utterance.

        Blocking, and intended to be called inside an executor. It is ``async``
        only to satisfy the provider Protocol.
        """
        segments, info = self._run(audio, language)
        text = "".join(segment.text for segment in segments).strip()
        return Transcript(
            text=text,
            language=getattr(info, "language", language or "el") or "el",
            confidence=_confidence(info),
            duration_s=audio.duration_s,
        )

    def transcribe_segments(
        self, audio: AudioChunk, *, language: str | None = None
    ) -> Iterator[tuple[str, bool]]:
        """Yield ``(text_so_far, is_final)`` as Whisper decodes.

        This is genuine incremental output, not simulated streaming: Whisper
        finalises one segment at a time and we surface each as it lands.

        Be aware of the honest limitation — a typical two-to-four second command
        decodes as a *single* segment, so in practice this fires once and the
        partial equals the final. It earns its keep on long dictation, and the
        interface exists so a genuinely streaming backend can slot in later
        without changing callers.
        """
        segments, _info = self._run(audio, language)
        accumulated = ""
        for segment in segments:
            accumulated += segment.text
            yield accumulated.strip(), False
        yield accumulated.strip(), True

    def _run(self, audio: AudioChunk, language: str | None) -> tuple[list[Any], Any]:
        if self._model is None:
            raise ProviderError("whisper model is not loaded")
        try:
            import numpy as np
        except ImportError as exc:
            raise ProviderError("numpy is required for transcription") from exc

        samples = np.frombuffer(audio.pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return [], None

        config = self._config
        try:
            segments, info = self._model.transcribe(
                samples,
                language=language or config.language,
                beam_size=config.beam_size,
                initial_prompt=config.initial_prompt,
                condition_on_previous_text=False,
                vad_filter=config.vad_filter,
                no_speech_threshold=config.no_speech_threshold,
                log_prob_threshold=config.log_prob_threshold,
                temperature=list(config.temperature),
            )
            return list(segments), info
        except Exception as exc:
            raise ProviderError(f"transcription failed: {exc}") from exc


def _confidence(info: Any) -> float:
    """Map Whisper's no-speech probability to a rough 0..1 confidence."""
    if info is None:
        return 0.0
    probability = getattr(info, "language_probability", None)
    return float(probability) if probability is not None else 1.0


def _explain_load_failure(config: WhisperConfig, device: str, exc: Exception) -> str:
    """Turn a model-load failure into something actionable.

    The CUDA case is the one that actually bites Windows users: CTranslate2 needs
    matching cuDNN and cuBLAS DLLs on PATH, and the error it raises otherwise is
    unhelpful.
    """
    text = str(exc).lower()
    if device == "cuda" and ("cudnn" in text or "cublas" in text or "library" in text):
        return (
            f"CUDA is present but CTranslate2 could not load its libraries "
            f"({exc}). Install the cuDNN 9 and cuBLAS runtime DLLs, or set "
            "stt.device = 'cpu' in config/user.toml."
        )
    if any(
        marker in text
        for marker in ("connection", "resolve", "offline", "403", "forbidden", "proxy", "timeout")
    ):
        return (
            f"could not download the {config.model!r} model and it is not cached. "
            "Run 'python -m bob fetch-models' while online."
        )
    return f"could not load whisper model {config.model!r} on {device}: {exc}"


@registry.register("stt", "faster-whisper")
def _factory(**kwargs: Any) -> FasterWhisperSTT:
    return FasterWhisperSTT(
        WhisperConfig(
            model=str(kwargs.get("model", "large-v3-turbo")),
            device=str(kwargs.get("device", "auto")),
            compute_type=str(kwargs.get("compute_type", "auto")),
            language=kwargs.get("language", "el"),
            beam_size=int(kwargs.get("beam_size", 5)),
            initial_prompt=kwargs.get("initial_prompt", GREEK_PROMPT),
        )
    )
