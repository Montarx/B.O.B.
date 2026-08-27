"""Asynchronous publish/subscribe event bus.

Design rules, chosen deliberately:

1. **Handlers are async and must not block.** A handler that needs to do real work
   should hand it to a task or an executor and return immediately.
2. **``publish`` awaits its handlers.** This makes tests deterministic and ordering
   comprehensible. Fire-and-forget is available via :meth:`publish_soon` for
   high-frequency signals (audio levels) where back-pressure is undesirable.
3. **One failing handler never breaks the bus.** Handler exceptions are captured and
   reported through ``on_handler_error``; other handlers still run.
4. **Thread-safety via one door.** :meth:`publish_threadsafe` is the only entry point
   for non-asyncio threads (the Qt GUI thread, audio callbacks). Everything else
   assumes the bus's own loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from typing import Final

from bob.core.events import Event, EventType

Handler = Callable[[Event], Awaitable[None]]

WILDCARD: Final = "*"

_log = logging.getLogger("bob.app.bus")


class Subscription:
    """Handle returned by :meth:`EventBus.subscribe`; cancel it to unsubscribe."""

    __slots__ = ("_active", "_bus", "_handler", "_key")

    def __init__(self, bus: EventBus, key: str, handler: Handler) -> None:
        self._bus = bus
        self._key = key
        self._handler = handler
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def cancel(self) -> None:
        if self._active:
            self._bus._remove(self._key, self._handler)
            self._active = False

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cancel()


class EventBus:
    """In-process async event bus."""

    def __init__(self, *, name: str = "bus") -> None:
        self._name = name
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._background: set[asyncio.Task[None]] = set()
        self._closed = False
        self._published = 0

    # -- subscription ----------------------------------------------------

    def subscribe(self, event_type: EventType | str, handler: Handler) -> Subscription:
        """Subscribe to one event type, or to ``"*"`` for every event."""
        key = str(event_type)
        self._handlers[key].append(handler)
        return Subscription(self, key, handler)

    def subscribe_many(
        self, event_types: Iterable[EventType | str], handler: Handler
    ) -> list[Subscription]:
        return [self.subscribe(t, handler) for t in event_types]

    def _remove(self, key: str, handler: Handler) -> None:
        try:
            self._handlers[key].remove(handler)
        except ValueError:
            pass

    def handler_count(self, event_type: EventType | str | None = None) -> int:
        if event_type is None:
            return sum(len(v) for v in self._handlers.values())
        return len(self._handlers[str(event_type)])

    @property
    def published_count(self) -> int:
        return self._published

    # -- publishing ------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """Deliver ``event`` to all matching handlers and wait for them to finish."""
        if self._closed:
            _log.debug("bus closed; dropping %s", event.type)
            return
        self._published += 1
        handlers = [*self._handlers[str(event.type)], *self._handlers[WILDCARD]]
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for handler, result in zip(handlers, results, strict=True):
            if isinstance(result, BaseException):
                self.on_handler_error(handler, event, result)

    def publish_soon(self, event: Event) -> None:
        """Fire-and-forget publish from inside the bus's own event loop."""
        if self._closed:
            return
        task = asyncio.create_task(self.publish(event))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def publish_threadsafe(self, loop: asyncio.AbstractEventLoop, event: Event) -> None:
        """Publish from a foreign thread (Qt GUI thread, audio device callback).

        This is the single supported bridge between B.O.B.'s threads and the bus.
        """
        if self._closed:
            return
        loop.call_soon_threadsafe(self.publish_soon, event)

    # -- error policy ----------------------------------------------------

    def on_handler_error(self, handler: Handler, event: Event, exc: BaseException) -> None:
        """Override in tests to assert on handler failures."""
        if isinstance(exc, asyncio.CancelledError):
            return
        name = getattr(handler, "__qualname__", repr(handler))
        _log.error("event handler %s failed on %s: %s", name, event.type, exc, exc_info=exc)

    # -- lifecycle -------------------------------------------------------

    async def aclose(self) -> None:
        """Stop accepting events and let in-flight background publishes settle."""
        self._closed = True
        pending = list(self._background)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._handlers.clear()

    def __repr__(self) -> str:
        return (
            f"<EventBus {self._name} handlers={self.handler_count()} published={self._published}>"
        )
