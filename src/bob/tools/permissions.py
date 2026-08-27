"""The permission broker: the one place that decides whether an action may run.

Policy is configuration (``security.policy``), not code. The only rule hard-wired
here is that HIGH-risk actions can never be silently auto-approved — the config
schema rejects ``high = "allow"``, and this module refuses it again at runtime.
Defence in depth, because this is the boundary that protects the user's machine.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from bob.config.schema import PolicyName, RiskName, SecuritySettings
from bob.core.bus import EventBus
from bob.core.events import ConfirmationRequested
from bob.tools.base import RiskLevel, ToolSpec

_log = logging.getLogger("bob.tools.permissions")


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PermissionVerdict:
    decision: Decision
    reason: str
    required_confirmation: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


#: Asked to confirm a risky action; returns True to approve.
#: Phase 1 wires this to the UI. Until then it defaults to refusing.
ConfirmFn = Callable[[ToolSpec, str], Awaitable[bool]]


async def deny_by_default(spec: ToolSpec, summary: str) -> bool:
    """Fallback confirmation handler: no interactive user, so nothing is approved."""
    _log.warning("no confirmation handler available; refusing %s", spec.name)
    return False


class PermissionBroker:
    """Evaluates a tool call against the configured risk policy."""

    def __init__(
        self,
        settings: SecuritySettings,
        bus: EventBus,
        *,
        confirm: ConfirmFn | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._confirm = confirm or deny_by_default

    def set_confirmation_handler(self, confirm: ConfirmFn) -> None:
        """Called by the UI layer once a human is actually there to answer."""
        self._confirm = confirm

    async def check(self, spec: ToolSpec, summary: str = "") -> PermissionVerdict:
        """Decide whether ``spec`` may execute, asking the user if policy says so."""
        if spec.name in self._settings.blocked_tools:
            return PermissionVerdict(Decision.DENY, "tool is blocked by configuration")

        policy: PolicyName = self._settings.policy.get(cast(RiskName, spec.risk.label), "confirm")

        # Hard floor: HIGH risk always asks, whatever the config claims.
        if spec.risk is RiskLevel.HIGH and policy == "allow":
            _log.error(
                "config tried to auto-allow HIGH risk tool %s; forcing confirmation",
                spec.name,
            )
            policy = "confirm"

        if policy == "deny":
            return PermissionVerdict(Decision.DENY, "policy denies this risk level")

        if policy == "allow":
            return PermissionVerdict(Decision.ALLOW, "policy allows this risk level")

        # policy == "confirm"
        await self._bus.publish(
            ConfirmationRequested(
                source="permissions",
                tool=spec.name,
                risk=spec.risk.label,
                summary=summary or spec.description,
            )
        )
        try:
            approved = await asyncio.wait_for(
                self._confirm(spec, summary or spec.description),
                timeout=self._settings.confirmation_timeout_s,
            )
        except TimeoutError:
            _log.warning("confirmation for %s timed out; treating as refusal", spec.name)
            return PermissionVerdict(
                Decision.DENY, "confirmation timed out", required_confirmation=True
            )

        return PermissionVerdict(
            Decision.ALLOW if approved else Decision.DENY,
            "user approved" if approved else "user refused",
            required_confirmation=True,
        )
