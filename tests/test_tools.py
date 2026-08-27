"""Tool validation, permissions, execution and audit.

This is the safety boundary. If any of these tests go soft, B.O.B. becomes
dangerous, so they are deliberately strict.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from bob.config.schema import SecuritySettings
from bob.core.bus import EventBus
from bob.tools.audit import AuditLog, redact
from bob.tools.base import RiskLevel, ToolContext, ToolResult, tool
from bob.tools.builtin import default_tools
from bob.tools.permissions import PermissionBroker
from bob.tools.registry import ToolRegistry

from .conftest import Recorder


class VolumeArgs(BaseModel):
    model_config = {"extra": "forbid"}
    level: int = Field(..., ge=0, le=100)


@tool("test.volume", "Set the volume.", VolumeArgs, risk=RiskLevel.LOW)
async def set_volume(args: VolumeArgs, ctx: ToolContext) -> ToolResult:
    return ToolResult.success(f"Ένταση στο {args.level}.", level=args.level)


@tool("test.delete", "Delete a file.", VolumeArgs, risk=RiskLevel.HIGH)
async def delete_thing(args: VolumeArgs, ctx: ToolContext) -> ToolResult:
    return ToolResult.success("deleted")


@tool("test.boom", "Always raises.", VolumeArgs, risk=RiskLevel.LOW)
async def boom(args: VolumeArgs, ctx: ToolContext) -> ToolResult:
    raise RuntimeError("tool internals exploded")


@tool("test.slow", "Never finishes.", VolumeArgs, risk=RiskLevel.LOW)
async def slow(args: VolumeArgs, ctx: ToolContext) -> ToolResult:
    await asyncio.sleep(10)
    return ToolResult.success("done")


def build_registry(
    bus: EventBus,
    tmp_path: Path,
    *,
    security: SecuritySettings | None = None,
    approve: bool | None = None,
) -> tuple[ToolRegistry, AuditLog, PermissionBroker]:
    settings = security or SecuritySettings()
    audit = AuditLog(tmp_path / "audit.jsonl", redact_keys=settings.redact_keys)
    broker = PermissionBroker(settings, bus)
    if approve is not None:

        async def confirm(spec: object, summary: str) -> bool:
            return bool(approve)

        broker.set_confirmation_handler(confirm)  # type: ignore[arg-type]
    registry = ToolRegistry(bus, broker, audit, default_timeout_s=0.2)
    registry.add_all([set_volume, delete_thing, boom, slow])
    return registry, audit, broker


# -- schema / validation ----------------------------------------------------


def test_schema_is_generated_from_the_pydantic_model() -> None:
    schema = set_volume.spec.json_schema()
    assert schema["function"]["name"] == "test.volume"
    assert "level" in schema["function"]["parameters"]["properties"]


async def test_out_of_range_argument_is_rejected_before_execution(
    bus: EventBus, tmp_path: Path
) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    result = await registry.execute("test.volume", {"level": 900})
    assert not result.ok
    assert "invalid arguments" in (result.error or "")


async def test_unexpected_argument_is_rejected(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    result = await registry.execute("test.volume", {"level": 10, "rm": "-rf /"})
    assert not result.ok


async def test_unknown_tool_is_rejected(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    result = await registry.execute("os.system", {"cmd": "format c:"})
    assert not result.ok
    assert "unknown tool" in (result.error or "")


async def test_valid_call_succeeds(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    result = await registry.execute("test.volume", {"level": 42})
    assert result.ok
    assert result.data["level"] == 42


# -- permissions ------------------------------------------------------------


async def test_low_risk_runs_without_asking(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    assert (await registry.execute("test.volume", {"level": 5})).ok


async def test_high_risk_is_denied_when_nobody_can_confirm(bus: EventBus, tmp_path: Path) -> None:
    """No UI attached means no approval — never a silent yes."""
    registry, _, _ = build_registry(bus, tmp_path)
    result = await registry.execute("test.delete", {"level": 1})
    assert not result.ok


async def test_high_risk_runs_only_after_approval(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path, approve=True)
    assert (await registry.execute("test.delete", {"level": 1})).ok


async def test_high_risk_refusal_is_honoured(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path, approve=False)
    result = await registry.execute("test.delete", {"level": 1})
    assert not result.ok


async def test_config_cannot_auto_allow_high_risk(bus: EventBus, tmp_path: Path) -> None:
    """Even if the policy dict is mutated at runtime, HIGH still asks."""
    security = SecuritySettings()
    security.policy["high"] = "allow"  # bypasses the schema validator on purpose
    registry, _, _ = build_registry(bus, tmp_path, security=security)
    result = await registry.execute("test.delete", {"level": 1})
    assert not result.ok, "HIGH risk must never execute unconfirmed"


async def test_blocked_tool_never_runs(bus: EventBus, tmp_path: Path) -> None:
    security = SecuritySettings(blocked_tools=["test.volume"])
    registry, _, _ = build_registry(bus, tmp_path, security=security, approve=True)
    result = await registry.execute("test.volume", {"level": 5})
    assert not result.ok


async def test_confirmation_timeout_counts_as_refusal(bus: EventBus, tmp_path: Path) -> None:
    security = SecuritySettings(confirmation_timeout_s=0.05)
    registry, _, broker = build_registry(bus, tmp_path, security=security)

    async def never_answers(spec: object, summary: str) -> bool:
        await asyncio.sleep(5)
        return True

    broker.set_confirmation_handler(never_answers)  # type: ignore[arg-type]
    result = await registry.execute("test.delete", {"level": 1})
    assert not result.ok


async def test_confirmation_request_is_announced(
    bus: EventBus, tmp_path: Path, recorder: Recorder
) -> None:
    """The UI learns about pending confirmations through the bus, not a callback."""
    registry, _, _ = build_registry(bus, tmp_path, approve=True)
    await registry.execute("test.delete", {"level": 1})
    assert recorder.of("tool.confirmation_requested")


async def test_dangerous_tools_can_be_hidden_from_the_model(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    names = {s["function"]["name"] for s in registry.schemas(max_risk=RiskLevel.LOW)}
    assert "test.volume" in names
    assert "test.delete" not in names


# -- failure containment ----------------------------------------------------


async def test_raising_tool_is_contained(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    result = await registry.execute("test.boom", {"level": 1})
    assert not result.ok
    assert "RuntimeError" in (result.error or "")


async def test_hanging_tool_times_out(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    result = await registry.execute("test.slow", {"level": 1})
    assert not result.ok
    assert "timed out" in (result.error or "")


# -- events -----------------------------------------------------------------


async def test_execution_publishes_start_and_finish(
    bus: EventBus, tmp_path: Path, recorder: Recorder
) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    await registry.execute("test.volume", {"level": 5})
    assert len(recorder.of("tool.execution_started")) == 1
    assert len(recorder.of("tool.execution_finished")) == 1


async def test_rejected_call_publishes_no_execution_events(
    bus: EventBus, tmp_path: Path, recorder: Recorder
) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    await registry.execute("test.volume", {"level": 999})
    assert recorder.of("tool.execution_started") == []


# -- audit ------------------------------------------------------------------


async def test_successful_action_is_audited(bus: EventBus, tmp_path: Path) -> None:
    registry, audit, _ = build_registry(bus, tmp_path)
    await registry.execute("test.volume", {"level": 7})
    entries = list(audit.read_all())
    assert len(entries) == 1
    assert entries[0]["tool"] == "test.volume"
    assert entries[0]["decision"] == "allowed"
    assert entries[0]["ok"] is True


async def test_denied_action_is_also_audited(bus: EventBus, tmp_path: Path) -> None:
    """Refusals are exactly the entries worth reviewing later."""
    registry, audit, _ = build_registry(bus, tmp_path, approve=False)
    await registry.execute("test.delete", {"level": 1})
    entries = list(audit.read_all())
    assert entries[0]["decision"] == "denied"


async def test_invalid_call_is_audited(bus: EventBus, tmp_path: Path) -> None:
    registry, audit, _ = build_registry(bus, tmp_path)
    await registry.execute("test.volume", {"level": 999})
    assert next(iter(audit.read_all()))["decision"] == "rejected"


def test_redaction_masks_nested_secrets() -> None:
    data = {"user": "niko", "password": "hunter2", "inner": {"api_key": "sk-123"}}
    out = redact(data, ["password", "api_key"])
    assert out["user"] == "niko"
    assert out["password"] == "***"
    assert out["inner"]["api_key"] == "***"


def test_audit_survives_a_corrupt_line(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(path)
    audit.record(tool="t", risk=RiskLevel.LOW, arguments={}, decision="allowed", ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    assert len(list(audit.read_all())) == 1


def test_disabled_audit_writes_nothing(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl", enabled=False)
    audit.record(tool="t", risk=RiskLevel.LOW, arguments={}, decision="allowed")
    assert list(audit.read_all()) == []


# -- built-ins --------------------------------------------------------------


def test_builtin_tools_are_all_low_risk() -> None:
    for t in default_tools():
        assert t.spec.risk is RiskLevel.LOW


def test_duplicate_registration_is_refused(bus: EventBus, tmp_path: Path) -> None:
    registry, _, _ = build_registry(bus, tmp_path)
    with pytest.raises(ValueError):
        registry.add(set_volume)


def test_tool_decorator_rejects_sync_functions() -> None:
    with pytest.raises(TypeError):

        @tool("test.sync", "Sync.", VolumeArgs)
        def not_async(args: VolumeArgs, ctx: ToolContext) -> ToolResult:  # type: ignore[misc]
            return ToolResult.success()
