"""Hosts the kernel's asyncio loop on its own thread.

The Qt event loop owns the GUI thread; this owns everything else. Separating
them is the decision recorded in ``ARCHITECTURE.md`` §3: it keeps the kernel
testable with no Qt installed, and it means a slow repaint can never stall the
kernel (or the reverse).

No Qt import here — this is the kernel side of the fence.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.kernel import Kernel

_log = logging.getLogger("bob.app.runtime")

T = TypeVar("T")


class KernelRuntime:
    """Owns a background asyncio loop and the :class:`Kernel` living on it."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._bus = EventBus(name="bob")
        self._kernel: Kernel | None = None
        self._start_error: BaseException | None = None

    # -- accessors -------------------------------------------------------

    @property
    def bus(self) -> EventBus:
        """Available before :meth:`start`, so subscribers can attach early."""
        return self._bus

    @property
    def kernel(self) -> Kernel:
        if self._kernel is None:
            raise RuntimeError("kernel runtime not started")
        return self._kernel

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("kernel runtime not started")
        return self._loop

    @property
    def running(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    # -- lifecycle -------------------------------------------------------

    def start(self, *, timeout: float = 30.0) -> None:
        """Start the loop thread and boot the kernel. Blocks until ready."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="bob-kernel", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("kernel did not become ready in time")
        if self._start_error is not None:
            raise self._start_error

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._boot())
        except BaseException as exc:  # surfaced to start() via _start_error
            self._start_error = exc
            self._ready.set()
            _log.exception("kernel thread failed during boot")
            return
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(self._shutdown())
            finally:
                loop.close()
                _log.info("kernel loop closed")

    async def _boot(self) -> None:
        self._kernel = Kernel(self._settings, bus=self._bus)
        await self._kernel.start()
        self._ready.set()

    async def _shutdown(self) -> None:
        if self._kernel is not None:
            await self._kernel.aclose()
        pending = [
            task for task in asyncio.all_tasks(self.loop) if task is not asyncio.current_task()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def stop(self, *, timeout: float = 10.0) -> None:
        """Stop the loop and join the thread. Safe to call more than once."""
        if self._loop is None or self._thread is None:
            return
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        self._thread = None

    # -- submitting work -------------------------------------------------

    def submit(self, coro: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        """Schedule a coroutine on the kernel loop from the GUI thread.

        This is the *only* supported way for the UI to reach the kernel.
        """
        if self._loop is None:
            raise RuntimeError("kernel runtime not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def call_soon(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Fire and forget, logging any failure rather than losing it."""
        future = self.submit(coro)

        def _report(fut: concurrent.futures.Future[Any]) -> None:
            try:
                fut.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception:
                _log.exception("background kernel task failed")

        future.add_done_callback(_report)
