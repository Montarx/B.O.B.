"""Append-only audit log of everything B.O.B. did or was refused.

One JSON object per line, never rewritten. If B.O.B. touches the machine, there is
a record of it — including the calls that were *denied*, which are exactly the ones
worth reviewing.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from bob.tools.base import RiskLevel

_log = logging.getLogger("bob.tools.audit")

_REDACTED = "***"


def redact(data: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """Mask values whose key name contains any sensitive term, recursively."""
    lowered = [k.lower() for k in keys]

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (_REDACTED if any(t in k.lower() for t in lowered) else scrub(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    result = scrub(data)
    return result if isinstance(result, dict) else {}


class AuditLog:
    """Writes audit records as JSON lines."""

    def __init__(
        self,
        path: Path,
        *,
        enabled: bool = True,
        redact_keys: Sequence[str] = (),
    ) -> None:
        self._path = path
        self._enabled = enabled
        self._redact_keys = list(redact_keys)
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        tool: str,
        risk: RiskLevel,
        arguments: dict[str, Any],
        decision: str,
        reason: str = "",
        ok: bool | None = None,
        duration_ms: float = 0.0,
        error: str | None = None,
        call_id: str = "",
    ) -> None:
        """Append one entry. Never raises — auditing must not break the action."""
        if not self._enabled:
            return
        entry = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "call_id": call_id,
            "tool": tool,
            "risk": risk.label,
            "args": redact(arguments, self._redact_keys),
            "decision": decision,
            "reason": reason,
            "ok": ok,
            "duration_ms": round(duration_ms, 2),
            "error": error,
        }
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.error("could not write audit entry: %s", exc)

    def read_all(self) -> Iterator[dict[str, Any]]:
        """Iterate stored entries, skipping any line corrupted by a crash mid-write."""
        if not self._path.is_file():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    _log.warning("skipping malformed audit line")
