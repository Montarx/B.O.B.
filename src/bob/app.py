"""Application entry points.

``python -m bob``            launches the desktop shell
``python -m bob --headless`` boots the kernel, runs a smoke check, exits
``python -m bob --dev``      launches the shell with developer tooling enabled

The headless path is kept because it is how the kernel is verified without a
display, and it is what CI runs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from bob import __identity__, __version__
from bob.config.loader import load_settings
from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.events import Event
from bob.core.kernel import Kernel
from bob.providers import load_all as _load_providers
from bob.utils import paths
from bob.utils.logging import setup_logging

_log = logging.getLogger("bob.app.main")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bob", description="B.O.B. — Beyond Orbit Buddy")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "devices", "fetch-models", "benchmark-stt"),
        help=(
            "run: the desktop shell (default) · devices: list microphones · "
            "fetch-models: download the VAD/STT models · "
            "benchmark-stt: compare STT configurations"
        ),
    )
    parser.add_argument(
        "--samples",
        type=Path,
        help="benchmark-stt: directory of 16-bit mono .wav samples",
    )
    parser.add_argument(
        "--models",
        help="benchmark-stt / fetch-models: comma-separated model names",
    )
    parser.add_argument("--device", default="auto", help="benchmark-stt: auto | cpu | cuda")
    parser.add_argument(
        "--compute-type",
        default="auto",
        help="benchmark-stt: auto | int8 | int8_float16 | float16 | float32",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="boot the kernel and run a smoke check without opening a window",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="enable the developer state switcher (F12) and demo runner (F9)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="start the scripted demonstration scenario immediately",
    )
    parser.add_argument("--version", action="version", version=f"B.O.B. {__version__}")
    return parser.parse_args(argv)


def _prepare(argv: list[str] | None = None) -> tuple[argparse.Namespace, Settings]:
    args = parse_args(argv)
    paths.ensure_dirs()
    settings = load_settings()
    setup_logging(settings.logging)
    _load_providers()
    return args, settings


# ---------------------------------------------------------------------------
# Headless
# ---------------------------------------------------------------------------


async def run_headless(settings: Settings) -> int:
    """Boot the kernel, exercise the tool pipeline, shut down."""
    _log.info("%s v%s (headless)", __identity__, __version__)

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


# ---------------------------------------------------------------------------
# Desktop
# ---------------------------------------------------------------------------


def run_desktop(settings: Settings, *, dev_tools: bool, demo: bool) -> int:
    """Launch the Qt shell. Imported lazily so headless mode needs no Qt."""
    try:
        from bob.ui.app import BobApplication
    except ImportError as exc:  # PySide6 not installed
        print(f'B.O.B.\'s interface needs PySide6.\n  pip install -e ".[ui]"\n({exc})')
        return 2

    app = BobApplication(settings, dev_tools=dev_tools or demo)
    if demo:
        from PySide6.QtCore import QTimer

        from bob.ui.intents import RunDemo

        QTimer.singleShot(1200, lambda: app.window.emit_intent(RunDemo(True)))
    return app.run()


def run_devices(settings: Settings) -> int:
    """List microphones, so a name can be put in ``config/user.toml``."""
    from bob.audio.capture import SoundDeviceBackend
    from bob.audio.devices import AudioDeviceError, describe_devices, select_device

    backend = SoundDeviceBackend()
    try:
        devices = backend.list_input_devices()
    except AudioDeviceError as exc:
        print(f"Could not enumerate microphones: {exc}")
        return 1

    print(describe_devices(devices))
    chosen = select_device(devices, settings.audio.input_device)
    if chosen is not None:
        print(f"\nB.O.B. would use: {chosen.label}")
    return 0


def run_benchmark_cli(settings: Settings, args: argparse.Namespace) -> int:
    """Compare STT configurations over the same Greek samples."""
    from bob.dev.benchmark import DEFAULT_MODELS, format_report, run_benchmark

    if not args.samples:
        print(
            "benchmark-stt needs samples:\n"
            "  python -m bob benchmark-stt --samples ./samples\n\n"
            "Put 16-bit mono .wav files there, each optionally beside a .txt\n"
            "containing the correct transcript (used to compute WER)."
        )
        return 2

    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else list(DEFAULT_MODELS)
    )
    try:
        reports = asyncio.run(
            run_benchmark(
                args.samples,
                models,
                device=args.device,
                compute_type=args.compute_type,
                language=settings.stt.language or "el",
                beam_size=settings.stt.beam_size,
            )
        )
    except FileNotFoundError as exc:
        print(f"{exc}")
        return 2
    print(format_report(reports))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point."""
    try:
        args, settings = _prepare(argv)
    except Exception as exc:
        print(f"B.O.B. failed to start: {exc}")
        return 1

    try:
        if args.command == "devices":
            return run_devices(settings)
        if args.command == "fetch-models":
            from bob.dev.fetch import fetch_all

            models = (
                [m.strip() for m in args.models.split(",") if m.strip()]
                if args.models
                else [settings.stt.model]
            )
            return fetch_all(models)
        if args.command == "benchmark-stt":
            return run_benchmark_cli(settings, args)
        if args.headless:
            return asyncio.run(run_headless(settings))
        return run_desktop(settings, dev_tools=args.dev, demo=args.demo)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("bob.app").exception("fatal error")
        print(f"B.O.B. failed to start: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
