"""Tool registry and executor.

:meth:`ToolRegistry.execute` is the single funnel every action passes through:

    validate args -> check permission -> audit -> run with timeout -> audit -> events

There is deliberately no way to run a tool that bypasses this sequence.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

from bob.core.bus import EventBus
from bob.core.errors import ToolNotFoundError, ToolValidationError
from bob.core.events import ToolExecutionFinished, ToolExecutionStarted
from bob.tools.audit import AuditLog
from bob.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from bob.tools.permissions import Decision, PermissionBroker

_log = logging.getLogger("bob.tools.registry")


class ToolRegistry:
    """Holds the available tools and executes them safely."""

    def __init__(
        self,
        bus: EventBus,
        broker: PermissionBroker,
        audit: AuditLog,
        *,
        default_timeout_s: float = 30.0,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._bus = bus
        self._broker = broker
        self._audit = audit
        self._timeout = default_timeout_s

    # -- registration ----------------------------------------------------

    def add(self, tool: Tool, *, replace: bool = False) -> None:
        name = tool.spec.name
        if name in self._tools and not replace:
            raise ValueError(f"tool {name!r} already registered")
        self._tools[name] = tool
        _log.debug("registered tool %s (%s)", name, tool.spec.risk.label)

    def add_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.add(tool)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(f"unknown tool {name!r}") from None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, *, max_risk: RiskLevel = RiskLevel.HIGH) -> list[dict[str, Any]]:
        """Function schemas to advertise to the LLM.

        ``max_risk`` lets a caller hide dangerous tools entirely from the model —
        the cheapest possible mitigation, since a tool the model cannot see is a
        tool it cannot ask for.
        """
        return [t.spec.json_schema() for t in self._tools.values() if t.spec.risk <= max_risk]

    # -- execution -------------------------------------------------------

    async def execute(
        self,
        name: str,
        raw_args: dict[str, Any] | None = None,
        *,
        ctx: ToolContext | None = None,
        timeout_s: float | None = None,
    ) -> ToolResult:
        """Validate, authorise, run and record a single tool call."""
        call_id = (ctx.call_id if ctx else "") or uuid.uuid4().hex[:12]
        raw_args = raw_args or {}

        try:
            tool = self.get(name)
        except ToolNotFoundError as exc:
            self._audit.record(
                tool=name,
                risk=RiskLevel.LOW,
                arguments=raw_args,
                decision="rejected",
                reason="unknown tool",
                ok=False,
                error=str(exc),
                call_id=call_id,
            )
            return ToolResult.failure(str(exc))

        spec = tool.spec

        # 1. Validate untrusted arguments against the tool's own schema.
        try:
            args = spec.validate_args(raw_args)
        except ToolValidationError as exc:
            self._audit.record(
                tool=name,
                risk=spec.risk,
                arguments=raw_args,
                decision="rejected",
                reason="invalid arguments",
                ok=False,
                error=str(exc),
                call_id=call_id,
            )
            return ToolResult.failure(str(exc))

        # 2. Authorise.
        summary = f"{spec.description} ({raw_args})" if raw_args else spec.description
        verdict = await self._broker.check(spec, summary)
        if verdict.decision is Decision.DENY:
            _log.info("denied %s: %s", name, verdict.reason)
            self._audit.record(
                tool=name,
                risk=spec.risk,
                arguments=raw_args,
                decision="denied",
                reason=verdict.reason,
                ok=False,
                call_id=call_id,
            )
            return ToolResult.failure(f"δεν επιτράπηκε: {verdict.reason}")

        # 3. Run.
        ctx = ctx or ToolContext(call_id=call_id)
        ctx = ToolContext(
            call_id=call_id,
            utterance=ctx.utterance,
            confirmed=verdict.required_confirmation,
            dry_run=ctx.dry_run,
        )

        await self._bus.publish(
            ToolExecutionStarted(source="tools", tool=name, call_id=call_id, risk=spec.risk.label)
        )
        started = time.perf_counter()
        error: str | None = None
        try:
            result = await asyncio.wait_for(tool.run(args, ctx), timeout=timeout_s or self._timeout)
        except TimeoutError:
            error = f"tool {name!r} timed out"
            result = ToolResult.failure(error)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a misbehaving tool must not take B.O.B. down
            _log.exception("tool %s raised", name)
            error = f"{type(exc).__name__}: {exc}"
            result = ToolResult.failure(error)

        duration_ms = (time.perf_counter() - started) * 1000

        # 4. Record and announce.
        self._audit.record(
            tool=name,
            risk=spec.risk,
            arguments=raw_args,
            decision="allowed",
            reason=verdict.reason,
            ok=result.ok,
            duration_ms=duration_ms,
            error=error or result.error,
            call_id=call_id,
        )
        await self._bus.publish(
            ToolExecutionFinished(
                source="tools",
                tool=name,
                call_id=call_id,
                ok=result.ok,
                duration_ms=duration_ms,
                summary=result.summary,
            )
        )
        return result
