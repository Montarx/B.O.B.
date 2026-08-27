"""Event bus behaviour."""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from bob.core.bus import EventBus
from bob.core.events import Event, EventType, TranscriptReady


async def test_publish_reaches_typed_and_wildcard_subscribers(bus: EventBus) -> None:
    typed: list[Event] = []
    wildcard: list[Event] = []

    async def on_typed(e: Event) -> None:
        typed.append(e)

    async def on_any(e: Event) -> None:
        wildcard.append(e)

    bus.subscribe(EventType.TRANSCRIPT_READY, on_typed)
    bus.subscribe("*", on_any)

    await bus.publish(TranscriptReady(source="t", text="γεια"))

    assert len(typed) == 1
    assert len(wildcard) == 1
    assert typed[0].text == "γεια"  # type: ignore[attr-defined]


async def test_unrelated_subscribers_do_not_receive_event(bus: EventBus) -> None:
    seen: list[Event] = []

    async def handler(e: Event) -> None:
        seen.append(e)

    bus.subscribe(EventType.ERROR_OCCURRED, handler)
    await bus.publish(TranscriptReady(source="t", text="x"))
    assert seen == []


async def test_publish_awaits_all_handlers(bus: EventBus) -> None:
    """Ordering must be deterministic: publish returns only when handlers are done."""
    done: list[str] = []

    async def slow(e: Event) -> None:
        await asyncio.sleep(0.01)
        done.append("slow")

    async def fast(e: Event) -> None:
        done.append("fast")

    bus.subscribe("*", slow)
    bus.subscribe("*", fast)
    await bus.publish(TranscriptReady(source="t", text="x"))
    assert sorted(done) == ["fast", "slow"]


async def test_one_failing_handler_does_not_stop_the_others(bus: EventBus) -> None:
    survived: list[Event] = []
    failures: list[BaseException] = []

    async def boom(e: Event) -> None:
        raise RuntimeError("handler exploded")

    async def good(e: Event) -> None:
        survived.append(e)

    bus.on_handler_error = lambda h, e, exc: failures.append(exc)  # type: ignore[method-assign]
    bus.subscribe("*", boom)
    bus.subscribe("*", good)

    await bus.publish(TranscriptReady(source="t", text="x"))

    assert len(survived) == 1
    assert isinstance(failures[0], RuntimeError)


async def test_subscription_cancel_stops_delivery(bus: EventBus) -> None:
    seen: list[Event] = []

    async def handler(e: Event) -> None:
        seen.append(e)

    sub = bus.subscribe("*", handler)
    await bus.publish(TranscriptReady(source="t", text="a"))
    sub.cancel()
    await bus.publish(TranscriptReady(source="t", text="b"))

    assert len(seen) == 1
    assert not sub.active


async def test_publish_soon_is_fire_and_forget(bus: EventBus) -> None:
    seen: list[Event] = []

    async def handler(e: Event) -> None:
        seen.append(e)

    bus.subscribe("*", handler)
    bus.publish_soon(TranscriptReady(source="t", text="a"))
    assert seen == []  # not delivered synchronously
    await asyncio.sleep(0)  # let the task run
    await asyncio.sleep(0)
    assert len(seen) == 1


async def test_closed_bus_drops_events(bus: EventBus) -> None:
    seen: list[Event] = []

    async def handler(e: Event) -> None:
        seen.append(e)

    bus.subscribe("*", handler)
    await bus.aclose()
    await bus.publish(TranscriptReady(source="t", text="a"))
    assert seen == []


async def test_publish_threadsafe_delivers_from_foreign_thread(bus: EventBus) -> None:
    """The single supported bridge for the Qt GUI thread and audio callbacks."""
    seen: list[Event] = []

    async def handler(e: Event) -> None:
        seen.append(e)

    bus.subscribe("*", handler)
    loop = asyncio.get_running_loop()

    await asyncio.to_thread(
        bus.publish_threadsafe, loop, TranscriptReady(source="thread", text="x")
    )
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(seen) == 1
    assert seen[0].source == "thread"


def test_events_are_immutable() -> None:
    event = TranscriptReady(source="t", text="x")
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        event.text = "changed"  # type: ignore[misc]
