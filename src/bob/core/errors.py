"""Exception hierarchy for B.O.B.

Every error raised deliberately by B.O.B. derives from :class:`BobError`, so callers
can distinguish "our" failures from genuine bugs escaping a third-party library.
"""

from __future__ import annotations


class BobError(Exception):
    """Base class for all deliberate B.O.B. errors."""


class ConfigError(BobError):
    """Configuration is missing, malformed, or internally inconsistent."""


class IllegalTransitionError(BobError):
    """A state transition was requested that the transition table forbids."""

    def __init__(self, current: object, requested: object) -> None:
        super().__init__(f"illegal transition {current} -> {requested}")
        self.current = current
        self.requested = requested


class ProviderError(BobError):
    """A provider (LLM, STT, TTS, ...) failed to fulfil a request."""


class ProviderNotFoundError(ProviderError):
    """No provider is registered under the requested kind/name."""


class ToolError(BobError):
    """A tool failed during execution."""


class ToolNotFoundError(ToolError):
    """No tool is registered under the requested name."""


class ToolValidationError(ToolError):
    """The arguments supplied to a tool did not satisfy its schema."""


class PermissionDeniedError(ToolError):
    """The permission broker refused to authorise a tool call."""
