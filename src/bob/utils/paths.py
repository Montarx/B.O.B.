"""Where B.O.B. keeps things on disk.

Everything user-writable lives outside the repository so a Git checkout stays clean
and an installed build (Phase 10) behaves identically to a dev checkout.
Set ``BOB_HOME`` to override — the test suite does exactly that.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "BOB"
APP_AUTHOR = "Montarx"


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Project root (the directory holding ``pyproject.toml``)."""
    return Path(__file__).resolve().parents[3]


def home() -> Path:
    """Root of B.O.B.'s writable data directory."""
    override = os.environ.get("BOB_HOME")
    base = Path(override) if override else Path(user_data_dir(APP_NAME, APP_AUTHOR))
    return base


def config_dir() -> Path:
    """Directory holding ``default.toml`` / ``user.toml`` / ``personas/``."""
    override = os.environ.get("BOB_CONFIG_DIR")
    if override:
        return Path(override)
    return repo_root() / "config"


def logs_dir() -> Path:
    return home() / "logs"


def data_dir() -> Path:
    return home() / "data"


def models_dir() -> Path:
    """Downloaded model weights (whisper, piper, wake word). Never committed."""
    return home() / "models"


def audit_path() -> Path:
    return home() / "audit" / "actions.jsonl"


def ensure_dirs() -> None:
    """Create the writable directory tree if it does not exist yet."""
    for path in (logs_dir(), data_dir(), models_dir(), audit_path().parent):
        path.mkdir(parents=True, exist_ok=True)
