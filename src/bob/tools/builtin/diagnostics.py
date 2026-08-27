"""Dependency-free diagnostic tools.

These exist so the tool pipeline is exercised end to end from Phase 0, and so a
user can always ask B.O.B. whether he is actually alive.
"""

from __future__ import annotations

import platform
import time

from pydantic import BaseModel, Field

from bob import __version__
from bob.tools.base import RiskLevel, ToolContext, ToolResult, tool

_STARTED = time.monotonic()


class PingArgs(BaseModel):
    """No arguments; declared explicitly so the schema is still well-formed."""

    model_config = {"extra": "forbid"}


class VersionArgs(BaseModel):
    model_config = {"extra": "forbid"}

    verbose: bool = Field(
        False, description="Include Python and OS details as well as B.O.B.'s version."
    )


@tool(
    "core.ping",
    "Check that B.O.B.'s core is responsive and report how long it has been running.",
    PingArgs,
    risk=RiskLevel.LOW,
    category="diagnostics",
)
async def ping(args: PingArgs, ctx: ToolContext) -> ToolResult:
    uptime = time.monotonic() - _STARTED
    return ToolResult.success(f"Ζωντανός, {uptime:.0f} δευτερόλεπτα.", uptime_s=uptime)


@tool(
    "core.version",
    "Report which version of B.O.B. is running.",
    VersionArgs,
    risk=RiskLevel.LOW,
    category="diagnostics",
)
async def version(args: VersionArgs, ctx: ToolContext) -> ToolResult:
    data: dict[str, str] = {"version": __version__}
    if args.verbose:
        data["python"] = platform.python_version()
        data["platform"] = platform.platform()
    return ToolResult.success(f"B.O.B. {__version__}", **data)
