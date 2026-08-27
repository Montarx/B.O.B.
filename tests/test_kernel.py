"""Kernel wiring and lifecycle."""

from __future__ import annotations

import pytest

from bob.config.loader import load_settings
from bob.config.schema import Settings
from bob.core.bus import EventBus
from bob.core.errors import ProviderNotFoundError
from bob.core.kernel import Kernel
from bob.core.states import BobState

from .conftest import Recorder


async def test_kernel_boots_to_idle(settings: Settings, bus: EventBus) -> None:
    kernel = Kernel(settings, bus=bus)
    assert kernel.state.state is BobState.OFFLINE
    async with kernel:
        assert kernel.state.state is BobState.IDLE
        assert kernel.started


async def test_boot_sequence_is_announced(
    settings: Settings, bus: EventBus, recorder: Recorder
) -> None:
    async with Kernel(settings, bus=bus):
        pass
    types = recorder.types()
    assert types.index("kernel.starting") < types.index("kernel.ready")
    assert "kernel.stopping" in types


async def test_all_providers_are_wired_from_config(settings: Settings, bus: EventBus) -> None:
    async with Kernel(settings, bus=bus) as kernel:
        info = kernel.describe()
        assert all(name is not None for name in info["providers"].values())
        assert info["providers"]["llm"] == "mock-llm"


async def test_persona_comes_from_the_config_file(settings: Settings, bus: EventBus) -> None:
    async with Kernel(settings, bus=bus) as kernel:
        assert "B.O.B." in kernel.persona


async def test_builtin_tools_are_registered(settings: Settings, bus: EventBus) -> None:
    async with Kernel(settings, bus=bus) as kernel:
        assert "core.ping" in kernel.tools
        assert "core.version" in kernel.tools


async def test_ping_tool_runs_through_the_full_pipeline(settings: Settings, bus: EventBus) -> None:
    async with Kernel(settings, bus=bus) as kernel:
        result = await kernel.tools.execute("core.ping")
        assert result.ok
        assert "uptime_s" in result.data


async def test_actions_land_in_the_audit_log(settings: Settings, bus: EventBus) -> None:
    async with Kernel(settings, bus=bus) as kernel:
        await kernel.tools.execute("core.version", {"verbose": True})
        entries = list(kernel.audit.read_all())
    assert entries[-1]["tool"] == "core.version"


async def test_bad_provider_name_fails_startup_into_error_state(
    clean_env: None, bus: EventBus
) -> None:
    settings = load_settings(overrides={"stt": {"provider": "nope"}})
    kernel = Kernel(settings, bus=bus)
    with pytest.raises(ProviderNotFoundError):
        await kernel.start()
    assert kernel.state.state is BobState.ERROR
    await kernel.aclose()


async def test_shutdown_is_idempotent(settings: Settings, bus: EventBus) -> None:
    kernel = Kernel(settings, bus=bus)
    await kernel.start()
    await kernel.aclose()
    await kernel.aclose()
    assert kernel.state.state is BobState.OFFLINE


async def test_start_is_idempotent(settings: Settings, bus: EventBus) -> None:
    kernel = Kernel(settings, bus=bus)
    await kernel.start()
    await kernel.start()
    assert kernel.state.state is BobState.IDLE
    await kernel.aclose()
