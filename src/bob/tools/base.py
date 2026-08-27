"""Tool definitions.

The rule that shapes this entire module: **the model never produces something we
execute.** It produces a tool *name* and a JSON *object of arguments*. The name must
already exist in the registry, and the arguments must validate against that tool's
Pydantic model before anything runs. There is no path from model output to a shell.

Every tool declares a :class:`RiskLevel`, which is what the permission broker gates
on. Risk is a property of the tool (and optionally of its arguments), never something
the model gets to assert about itself.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from bob.core.errors import ToolValidationError


class RiskLevel(IntEnum):
    """How much damage a tool can do if B.O.B. misunderstands."""

    LOW = 1
    """Reversible and harmless: open an app, read CPU usage, change volume."""

    MEDIUM = 2
    """Disruptive but recoverable: close an app, move a file, change a setting."""

    HIGH = 3
    """Destructive, irreversible, outward-facing or privacy-sensitive:
    delete files, uninstall, shut down, send a message, spend money."""

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Ambient information a tool may need, passed explicitly rather than imported."""

    call_id: str = ""
    utterance: str = ""
    confirmed: bool = False
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool gives back.

    ``summary`` is written for B.O.B. to read aloud or reason about; ``data`` is
    the structured payload for programmatic use.
    """

    ok: bool
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def success(cls, summary: str = "", **data: Any) -> ToolResult:
        return cls(ok=True, summary=summary, data=data)

    @classmethod
    def failure(cls, error: str, summary: str = "") -> ToolResult:
        return cls(ok=False, error=error, summary=summary or error)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Everything the registry, the permission broker and the LLM need to know."""

    name: str
    description: str
    args_model: type[BaseModel]
    risk: RiskLevel = RiskLevel.LOW
    category: str = "general"
    #: Set for tools that touch the network or the outside world; surfaced in the UI.
    outward_facing: bool = False

    def json_schema(self) -> dict[str, Any]:
        """OpenAI/Ollama-style function schema, generated from the Pydantic model."""
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    def validate_args(self, raw: dict[str, Any]) -> BaseModel:
        """Turn untrusted model output into a typed, validated arguments object."""
        try:
            return self.args_model.model_validate(raw)
        except ValidationError as exc:
            raise ToolValidationError(
                f"invalid arguments for tool {self.name!r}: {exc.errors()}"
            ) from exc


@runtime_checkable
class Tool(Protocol):
    """A callable capability B.O.B. can invoke."""

    @property
    def spec(self) -> ToolSpec: ...

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...


RunFn = Callable[[Any, ToolContext], Awaitable[ToolResult]]


class FunctionTool[ArgsT: BaseModel]:
    """Adapter wrapping a plain async function as a :class:`Tool`."""

    __slots__ = ("_fn", "_spec")

    def __init__(self, spec: ToolSpec, fn: RunFn) -> None:
        self._spec = spec
        self._fn = fn

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        return await self._fn(args, ctx)

    def __repr__(self) -> str:
        return f"<FunctionTool {self._spec.name} risk={self._spec.risk.label}>"


def tool(
    name: str,
    description: str,
    args_model: type[BaseModel],
    *,
    risk: RiskLevel = RiskLevel.LOW,
    category: str = "general",
    outward_facing: bool = False,
) -> Callable[[RunFn], FunctionTool[BaseModel]]:
    """Decorator turning ``async def fn(args, ctx) -> ToolResult`` into a tool."""

    def decorator(fn: RunFn) -> FunctionTool[BaseModel]:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"tool {name!r} must be an async function")
        spec = ToolSpec(
            name=name,
            description=description,
            args_model=args_model,
            risk=risk,
            category=category,
            outward_facing=outward_facing,
        )
        return FunctionTool(spec, fn)

    return decorator
