"""Shared fixtures.

Every test runs against an isolated ``BOB_HOME`` so nothing touches the developer's
real logs, audit trail or data directory.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from bob.config.loader import load_settings
from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.events import Event
from bob.providers import mock as _mock_providers  # noqa: F401 — registers mocks
from bob.utils import paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "bobhome"
    monkeypatch.setenv("BOB_HOME", str(home))
    paths.ensure_dirs()
    yield home


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove BOB__* overrides so a stray shell variable cannot break a test."""
    for key in list(os.environ):
        if key.startswith("BOB__"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings(clean_env: None) -> Settings:
    """Real settings loaded from the committed config/default.toml."""
    return load_settings()


@pytest.fixture
def bus() -> EventBus:
    return EventBus(name="test")


class Recorder:
    """Collects every event published on a bus, for assertions."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def __call__(self, event: Event) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type.value for e in self.events]

    def of(self, event_type: str) -> list[Event]:
        return [e for e in self.events if e.type.value == event_type]


@pytest.fixture
def recorder(bus: EventBus) -> Recorder:
    rec = Recorder()
    bus.subscribe("*", rec)
    return rec
