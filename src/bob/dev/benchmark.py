"""STT benchmark harness.

Exists because picking a Whisper model from a blog post is guesswork: Greek
accuracy, your CPU, your GPU's VRAM and your microphone all matter, and only you
can measure them. This runs several configurations over the *same* recordings and
prints a table.

Usage::

    python -m bob benchmark-stt --samples ./samples
    python -m bob benchmark-stt --samples ./samples --models small,medium,large-v3-turbo

A sample is a 16-bit mono WAV. Put an optional ``.txt`` next to it with the
correct transcript and the harness will compute WER and CER as well.

Deliberately not overengineered: no plotting, no database, no statistical
modelling. A table you can read and act on.
"""

from __future__ import annotations

import gc
import logging
import sys
import time
import unicodedata
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bob.providers.base import AudioChunk
from bob.providers.stt.faster_whisper import (
    GREEK_PROMPT,
    FasterWhisperSTT,
    WhisperConfig,
    resolve_compute_type,
    resolve_device,
)

_log = logging.getLogger("bob.ai.benchmark")

#: Sensible defaults. distil-whisper is deliberately absent: it is English-only
#: and therefore not a candidate for a Greek assistant.
DEFAULT_MODELS: tuple[str, ...] = ("small", "medium", "large-v3-turbo", "large-v3")


@dataclass(frozen=True, slots=True)
class Sample:
    """One recording, with an optional reference transcript."""

    path: Path
    pcm: bytes
    sample_rate: int
    reference: str = ""

    @property
    def duration_s(self) -> float:
        return (len(self.pcm) // 2) / self.sample_rate if self.sample_rate else 0.0

    @property
    def name(self) -> str:
        return self.path.stem


@dataclass(slots=True)
class RunResult:
    """One model against one sample."""

    model: str
    device: str
    compute_type: str
    sample: str
    duration_s: float
    transcribe_s: float
    transcript: str
    wer: float | None = None
    cer: float | None = None
    error: str = ""

    @property
    def rtf(self) -> float:
        """Real-time factor. Below 1.0 means faster than the audio is long."""
        return self.transcribe_s / self.duration_s if self.duration_s else 0.0


@dataclass(slots=True)
class ModelReport:
    """Everything measured for one configuration."""

    model: str
    device: str
    compute_type: str
    load_s: float = 0.0
    peak_rss_mb: float = 0.0
    runs: list[RunResult] = field(default_factory=list)
    error: str = ""

    @property
    def mean_rtf(self) -> float:
        values = [r.rtf for r in self.runs if not r.error]
        return sum(values) / len(values) if values else 0.0

    @property
    def mean_wer(self) -> float | None:
        values = [r.wer for r in self.runs if r.wer is not None]
        return sum(values) / len(values) if values else None

    @property
    def mean_cer(self) -> float | None:
        values = [r.cer for r in self.runs if r.cer is not None]
        return sum(values) / len(values) if values else None


# ---------------------------------------------------------------------------
# Sample loading
# ---------------------------------------------------------------------------


def load_wav(path: Path) -> tuple[bytes, int]:
    """Read a mono 16-bit WAV, downmixing stereo if needed."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if width != 2:
        raise ValueError(f"{path.name}: expected 16-bit audio, got {width * 8}-bit")
    if channels == 2:
        import array

        samples = array.array("h")
        samples.frombytes(frames)
        mono = array.array(
            "h", [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples) - 1, 2)]
        )
        frames = mono.tobytes()
    return frames, rate


def load_samples(directory: Path) -> list[Sample]:
    """Load every WAV in ``directory``, pairing each with an optional .txt."""
    if not directory.is_dir():
        raise FileNotFoundError(f"sample directory not found: {directory}")
    samples: list[Sample] = []
    for path in sorted(directory.glob("*.wav")):
        try:
            pcm, rate = load_wav(path)
        except Exception as exc:
            _log.warning("skipping %s: %s", path.name, exc)
            continue
        reference_path = path.with_suffix(".txt")
        reference = (
            reference_path.read_text(encoding="utf-8").strip() if reference_path.is_file() else ""
        )
        samples.append(Sample(path=path, pcm=pcm, sample_rate=rate, reference=reference))
    return samples


# ---------------------------------------------------------------------------
# Error metrics
# ---------------------------------------------------------------------------


def normalise_greek(text: str) -> str:
    """Normalise for scoring: casefold, drop accents and punctuation.

    Accents are stripped for the *metric only*. Greek accents are meaningful and
    B.O.B. keeps them in real transcripts; but scoring a model down because it
    wrote "ανοιξε" rather than "άνοιξε" would hide the differences that matter
    for command recognition.
    """
    decomposed = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch) and (ch.isalnum() or ch.isspace())
    )
    return " ".join(stripped.split())


def _levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, start=1):
        current = [i]
        for j, item_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (item_a != item_b),  # substitution
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalise_greek(reference).split()
    hyp = normalise_greek(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def character_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalise_greek(reference).replace(" ", "")
    hyp = normalise_greek(hypothesis).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(list(ref), list(hyp)) / len(ref)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _peak_rss_mb() -> float:
    """Process peak RSS, where the platform reports it."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is KiB on Linux but bytes on macOS, so the divisor differs.
        divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
        return peak / divisor
    except Exception:
        pass
    try:
        import psutil

        return float(psutil.Process().memory_info().rss) / (1024 * 1024)
    except Exception:
        return 0.0


async def benchmark_model(
    model: str,
    samples: Sequence[Sample],
    *,
    device: str = "auto",
    compute_type: str = "auto",
    language: str = "el",
    beam_size: int = 5,
    use_prompt: bool = True,
) -> ModelReport:
    """Load one configuration and run every sample through it."""
    resolved_device = resolve_device(device)
    resolved_compute = resolve_compute_type(resolved_device, compute_type)
    report = ModelReport(model=model, device=resolved_device, compute_type=resolved_compute)

    provider = FasterWhisperSTT(
        WhisperConfig(
            model=model,
            device=device,
            compute_type=compute_type,
            language=language,
            beam_size=beam_size,
            initial_prompt=GREEK_PROMPT if use_prompt else None,
        )
    )
    try:
        await provider.start()
    except Exception as exc:
        report.error = str(exc)
        return report

    report.load_s = provider.load_seconds

    for sample in samples:
        chunk = AudioChunk(pcm=sample.pcm, sample_rate=sample.sample_rate)
        started = time.perf_counter()
        try:
            transcript = await provider.transcribe(chunk, language=language)
            elapsed = time.perf_counter() - started
            run = RunResult(
                model=model,
                device=resolved_device,
                compute_type=resolved_compute,
                sample=sample.name,
                duration_s=sample.duration_s,
                transcribe_s=elapsed,
                transcript=transcript.text,
            )
            if sample.reference:
                run.wer = word_error_rate(sample.reference, transcript.text)
                run.cer = character_error_rate(sample.reference, transcript.text)
        except Exception as exc:
            run = RunResult(
                model=model,
                device=resolved_device,
                compute_type=resolved_compute,
                sample=sample.name,
                duration_s=sample.duration_s,
                transcribe_s=time.perf_counter() - started,
                transcript="",
                error=str(exc),
            )
        report.runs.append(run)

    report.peak_rss_mb = _peak_rss_mb()
    await provider.aclose()
    gc.collect()
    return report


def format_report(reports: Sequence[ModelReport], *, verbose: bool = True) -> str:
    """Render a readable table."""
    lines: list[str] = []
    lines.append("")
    lines.append("B.O.B. — STT benchmark")
    lines.append("=" * 78)
    header = (
        f"{'model':<20} {'device':<6} {'compute':<12} {'load':>7} "
        f"{'RTF':>7} {'WER':>7} {'CER':>7} {'peak MB':>9}"
    )
    lines.append(header)
    lines.append("-" * 78)

    for report in reports:
        if report.error:
            lines.append(f"{report.model:<20} FAILED: {report.error[:52]}")
            continue
        wer = f"{report.mean_wer:.1%}" if report.mean_wer is not None else "—"
        cer = f"{report.mean_cer:.1%}" if report.mean_cer is not None else "—"
        lines.append(
            f"{report.model:<20} {report.device:<6} {report.compute_type:<12} "
            f"{report.load_s:>6.1f}s {report.mean_rtf:>7.2f} {wer:>7} {cer:>7} "
            f"{report.peak_rss_mb:>9.0f}"
        )

    lines.append("-" * 78)
    lines.append("RTF = transcribe time / audio duration. Below 1.00 is faster than real time.")
    if any(r.mean_wer is not None for r in reports):
        lines.append("WER/CER computed on accent-insensitive, punctuation-free text.")
    else:
        lines.append("No reference transcripts found — add a .txt beside each .wav for WER.")

    if verbose:
        lines.append("")
        lines.append("Transcripts")
        lines.append("=" * 78)
        for report in reports:
            if report.error:
                continue
            lines.append(f"\n[{report.model} / {report.device} / {report.compute_type}]")
            for run in report.runs:
                if run.error:
                    lines.append(f"  {run.sample:<22} ERROR: {run.error[:44]}")
                    continue
                score = f" (WER {run.wer:.0%})" if run.wer is not None else ""
                lines.append(
                    f"  {run.sample:<22} {run.transcribe_s:>5.2f}s RTF {run.rtf:.2f}{score}"
                )
                lines.append(f"      {run.transcript}")
    lines.append("")
    return "\n".join(lines)


async def run_benchmark(
    samples_dir: Path,
    models: Sequence[str] = DEFAULT_MODELS,
    *,
    device: str = "auto",
    compute_type: str = "auto",
    language: str = "el",
    beam_size: int = 5,
) -> list[ModelReport]:
    """Load samples and benchmark every model. Returns the reports."""
    samples = load_samples(samples_dir)
    if not samples:
        raise FileNotFoundError(f"no .wav samples found in {samples_dir}")

    _log.info(
        "benchmarking %d model(s) over %d sample(s), %.1fs of audio",
        len(models),
        len(samples),
        sum(s.duration_s for s in samples),
    )

    reports: list[ModelReport] = []
    for model in models:
        print(f"  … loading {model}", flush=True)
        report = await benchmark_model(
            model,
            samples,
            device=device,
            compute_type=compute_type,
            language=language,
            beam_size=beam_size,
        )
        reports.append(report)
    return reports
