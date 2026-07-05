"""Tool protocol and result type.

A ``Tool`` is a stateless object: it can be registered once and invoked
many times across sessions, each time receiving the appropriate runtime.
That keeps ``ToolRegistry`` cheap to construct and trivially thread-safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


@dataclass(frozen=True)
class ToolResult:
    """Structured output of a tool invocation.

    ``output`` is the human-readable payload (what we put in a ToolResult
    Event today, what we'd feed to LangGraph state tomorrow). ``truncated``
    records whether the runtime cut the output for safety. ``metadata``
    carries structured side information (counts, file paths …).
    """

    output: str
    truncated: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """Stateless, runtime-aware capability.

    Implementations override ``name``, ``description`` and ``run``.
    Tools never hold per-call state — sessions rely on ``ToolRuntime``.
    """

    name: str
    description: str

    def run(self, runtime: ToolRuntime, **kwargs: Any) -> ToolResult:
        ...


__all__ = ["Tool", "ToolResult"]
