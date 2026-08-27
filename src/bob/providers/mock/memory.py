"""In-memory mock memory provider."""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import Any

from bob.providers.base import MemoryRecord
from bob.providers.registry import registry


class MockMemory:
    """Dict-backed store with naive substring recall.

    Phase 7 replaces the recall implementation with embeddings; the interface and
    the "deliberate, inspectable, deletable" semantics stay exactly as they are.
    """

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    @property
    def name(self) -> str:
        return "mock-memory"

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def remember(
        self,
        text: str,
        *,
        kind: str = "fact",
        tags: Sequence[str] = (),
        source: str = "user",
    ) -> MemoryRecord:
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            text=text,
            kind=kind,  # type: ignore[arg-type]
            tags=tuple(tags),
            created_at=time.time(),
            source=source,
        )
        self._records[record.id] = record
        return record

    async def recall(self, query: str, *, limit: int = 8) -> list[MemoryRecord]:
        terms = [t for t in query.lower().split() if t]
        scored: list[tuple[float, MemoryRecord]] = []
        for record in self._records.values():
            haystack = f"{record.text} {' '.join(record.tags)}".lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                scored.append((hits / max(len(terms), 1), record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [rec for _, rec in scored[:limit]]

    async def forget(self, record_id: str) -> bool:
        return self._records.pop(record_id, None) is not None

    async def list_all(self, *, kind: str | None = None) -> list[MemoryRecord]:
        records = list(self._records.values())
        if kind:
            records = [r for r in records if r.kind == kind]
        return sorted(records, key=lambda r: r.created_at)


@registry.register("memory", "mock")
def _factory(**kwargs: Any) -> MockMemory:
    return MockMemory()
