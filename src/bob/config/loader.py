"""Layered configuration loading.

Precedence, lowest to highest:

1. Field defaults in :mod:`bob.config.schema`
2. ``config/default.toml``      — committed, the shared baseline
3. ``config/user.toml``         — gitignored, the user's personal overrides
4. ``BOB__SECTION__KEY`` env vars — for CI, scripts and one-off runs
5. ``.env`` / environment       — secrets only, never written back

Splitting 2 and 3 means an update to the project's defaults never clobbers the
user's settings, and the user's settings never leak into Git.
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from bob.config.schema import Secrets, Settings
from bob.core.errors import ConfigError
from bob.utils import paths

_log = logging.getLogger("bob.app.config")

ENV_PREFIX = "BOB__"
ENV_DELIMITER = "__"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base``, returning a new dict."""
    result = deepcopy(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = deepcopy(value)
    return result


def _coerce(raw: str) -> Any:
    """Interpret an env var value as JSON when possible, else as a plain string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def env_overrides(environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Translate ``BOB__LLM__MODEL=foo`` into ``{"llm": {"model": "foo"}}``."""
    source = os.environ if environ is None else environ
    out: dict[str, Any] = {}
    for key, raw in source.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX) :].lower().split(ENV_DELIMITER)
        if not path or not all(path):
            _log.warning("ignoring malformed config env var %s", key)
            continue
        cursor = out
        for part in path[:-1]:
            nxt = cursor.setdefault(part, {})
            if not isinstance(nxt, dict):  # a scalar already claimed this key
                _log.warning("ignoring conflicting config env var %s", key)
                break
            cursor = nxt
        else:
            cursor[path[-1]] = _coerce(raw)
    return out


def load_settings(
    *,
    config_dir: Path | None = None,
    environ: dict[str, str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Build the validated :class:`Settings` object.

    ``overrides`` is applied last and exists for tests and command-line flags.
    """
    directory = config_dir or paths.config_dir()

    data = _read_toml(directory / "default.toml")
    data = deep_merge(data, _read_toml(directory / "user.toml"))
    data = deep_merge(data, env_overrides(environ))
    if overrides:
        data = deep_merge(data, overrides)

    # Secrets never come from TOML; refuse them loudly if someone tries.
    if "secrets" in data:
        raise ConfigError("secrets must not be defined in TOML — use environment variables or .env")

    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration:\n{exc}") from exc

    settings.secrets = Secrets()
    return settings


def load_persona(name: str, *, config_dir: Path | None = None) -> str:
    """Load the persona prompt text.

    B.O.B.'s personality lives in ``config/personas/<name>.md`` and nowhere else.
    Changing how he talks must never mean changing Python code.
    """
    directory = config_dir or paths.config_dir()
    path = directory / "personas" / f"{name}.md"
    if not path.is_file():
        raise ConfigError(f"persona file not found: {path}")
    return path.read_text(encoding="utf-8").strip()
