"""Logging setup.

Four separate streams so debugging is a matter of opening the right file rather
than grepping one giant log:

===============  ==================================================
``app.log``      lifecycle, config, state machine, UI, audio plumbing
``ai.log``       prompts, model choices, token streams, tool selection
``tools.log``    tool execution and permission decisions
``errors.log``   every WARNING+ from all channels, in one place
===============  ==================================================

Loggers are named ``bob.app.*``, ``bob.ai.*``, ``bob.tools.*``. Modules call
``logging.getLogger("bob.ai.brain")`` and never configure handlers themselves.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

from bob.config.schema import LoggingSettings
from bob.utils import paths

CHANNELS = ("app", "ai", "tools")

_configured = False


class JsonLineFormatter(logging.Formatter):
    """One JSON object per line — greppable by humans, parseable by tools."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "bob", None)
        if isinstance(extra, dict):
            payload |= extra
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Compact, aligned console output. No colour codes — Windows terminals vary."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)-22s %(message)s", "%H:%M:%S")


def _file_handler(path: Path, level: int, settings: LoggingSettings) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setLevel(level)
    handler.setFormatter(JsonLineFormatter() if settings.json_files else ConsoleFormatter())
    return handler


def setup_logging(settings: LoggingSettings | None = None, *, log_dir: Path | None = None) -> None:
    """Install B.O.B.'s handlers. Safe to call twice; the second call is a no-op."""
    global _configured
    if _configured:
        return

    settings = settings or LoggingSettings()
    directory = log_dir or paths.logs_dir()
    level = getattr(logging, settings.level)

    root = logging.getLogger("bob")
    root.setLevel(level)
    root.propagate = False
    root.handlers.clear()

    if settings.console:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(level)
        console.setFormatter(ConsoleFormatter())
        root.addHandler(console)

    # Everything WARNING+ lands in one place, whatever channel produced it.
    root.addHandler(_file_handler(directory / "errors.log", logging.WARNING, settings))

    for channel in CHANNELS:
        logger = logging.getLogger(f"bob.{channel}")
        logger.setLevel(level)
        logger.addHandler(_file_handler(directory / f"{channel}.log", level, settings))

    _configured = True


def reset_logging() -> None:
    """Tear handlers down again — used by the test suite."""
    global _configured
    for name in ("bob", *(f"bob.{c}" for c in CHANNELS)):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
    _configured = False
