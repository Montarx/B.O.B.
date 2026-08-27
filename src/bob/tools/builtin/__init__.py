"""Built-in tools.

Phase 0 ships only dependency-free diagnostics. Real capabilities (apps, files,
volume, processes, Steam) arrive in Phase 6 as separate modules registered here.
"""

from bob.tools.base import Tool
from bob.tools.builtin.diagnostics import ping, version


def default_tools() -> list[Tool]:
    """The tools every B.O.B. instance starts with."""
    return [ping, version]


__all__ = ["default_tools", "ping", "version"]
