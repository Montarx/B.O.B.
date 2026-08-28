"""Model downloads.

Kept as an explicit command rather than a silent first-run download, because
several gigabytes appearing unannounced is not something software should do. It
also gives a clear place to fail with an actionable message when a corporate
proxy or a firewall blocks Hugging Face.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path

from bob.providers.stt.faster_whisper import KNOWN_MODELS
from bob.providers.vad.silero import MODEL_URL, model_path
from bob.utils import paths

_log = logging.getLogger("bob.app.fetch")


def fetch_silero(*, force: bool = False, timeout: float = 60.0) -> Path:
    """Download the Silero VAD model (~1.8 MB)."""
    destination = model_path()
    if destination.is_file() and not force:
        print(f"  VAD model already present: {destination}")
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading Silero VAD -> {destination}")
    temporary = destination.with_suffix(".part")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=timeout) as response:
            temporary.write_bytes(response.read())
    except (urllib.error.URLError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"could not download the Silero VAD model: {exc}\n"
            f"  Download it manually from {MODEL_URL}\n"
            f"  and save it as {destination}"
        ) from exc

    if temporary.stat().st_size < 100_000:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("downloaded VAD model looks truncated; try again")

    temporary.replace(destination)
    print(f"  ok ({destination.stat().st_size / 1024:.0f} KB)")
    return destination


def fetch_whisper(model: str) -> None:
    """Warm the faster-whisper cache for one model."""
    if model not in KNOWN_MODELS:
        print(f"  note: {model!r} is not a name B.O.B. knows; trying anyway")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError('faster-whisper is not installed: pip install -e ".[voice]"') from exc

    target = paths.models_dir() / "whisper"
    target.mkdir(parents=True, exist_ok=True)
    print(f"  downloading whisper {model} -> {target}")
    try:
        WhisperModel(model, device="cpu", compute_type="int8", download_root=str(target))
    except Exception as exc:
        raise RuntimeError(
            f"could not download whisper {model!r}: {exc}\n"
            "  Check your network, or set HF_ENDPOINT if you use a mirror."
        ) from exc
    print(f"  ok: {model}")


def fetch_all(models: list[str] | None = None) -> int:
    """Fetch everything Phase 2 needs. Returns a process exit code."""
    print("Fetching B.O.B.'s models\n")
    failures = 0

    try:
        fetch_silero()
    except RuntimeError as exc:
        print(f"  FAILED: {exc}")
        failures += 1

    for model in models or []:
        try:
            fetch_whisper(model)
        except RuntimeError as exc:
            print(f"  FAILED: {exc}")
            failures += 1

    print()
    if failures:
        print(f"{failures} download(s) failed.")
        return 1
    print("All models ready.")
    return 0
