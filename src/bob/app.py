"""Application entry point (headless).

Phase 0 has no window. Running ``python -m bob`` boots the kernel with mock
providers, prints what it wired up, exercises a tool, and shuts down. It exists to
prove the foundation works — Phase 1 replaces this with the Qt shell, which will
boot the exact same kernel.
"""

from __future__ import annotations

import asyncio
import logging

from bob import __identity__, __version__
from bob.config.loader import load_settings
from bob.core.bus import EventBus
from bob.core.events import Event
from bob.core.kernel import Kernel
from bob.providers import mock as _mock_providers  # noqa: F401 — registers mocks
from bob.utils import paths
from bob.utils.logging import setup_logging

_log = logging.getLogger("bob.app.main")


async def run_headless() -> int:
    """Boot the kernel, run a smoke check, shut down. Returns a process exit code."""
    paths.ensure_dirs()
    settings = load_settings()
    setup_logging(settings.logging)

    _log.info("%s v%s", __identity__, __version__)

    bus = EventBus(name="bob")
    trace: list[str] = []

    async def log_everything(event: Event) -> None:
        trace.append(event.type.value)
        _log.debug("event %s | %s", event.type.value, event.describe())

    bus.subscribe("*", log_everything)

    kernel = Kernel(settings, bus=bus)
    async with kernel:
        info = kernel.describe()
        print(f"\n{__identity__}  v{__version__}")
        print(f"  state     : {info['state']}")
        print(f"  persona   : {info['persona']} ({len(kernel.persona)} chars)")
        print("  providers :")
        for kind, name in info["providers"].items():
            print(f"      {kind:<9} {name}")
        print(f"  tools     : {', '.join(info['tools'])}")
        print(f"  logs      : {paths.logs_dir()}")
        print(f"  audit     : {kernel.audit.path}")

        result = await kernel.tools.execute("core.ping")
        print(f"\n  core.ping -> ok={result.ok} {result.summary}")

    print(f"  events    : {len(trace)} published\n")
    return 0


def main() -> int:
    """Console-script entry point."""
    try:
        return asyncio.run(run_headless())
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # last-resort guard so the user sees a real message
        logging.getLogger("bob.app").exception("fatal error")
        print(f"B.O.B. failed to start: {exc}")
        return 1
