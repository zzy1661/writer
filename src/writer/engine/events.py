"""Event data class hierarchy for the agent engine.

Events are the public contract between ``writer.engine`` and its consumers
(REPL, future EngineSession, tests). They are immutable so consumers can
freely ``match`` on them without defensive copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from writer.routing import AgentAction


DoneReason = Literal[
    "answered",
    "command_pending",
    "tool_pending",
    "workflow_pending",
    "ask_user",
    "aborted",
    "tool_completed",
    "tool_loop_completed",
]


@dataclass(frozen=True)
class Event:
    """Base class for all engine events."""


@dataclass(frozen=True)
class TextChunk(Event):
    """A chunk of human-readable text, optionally followed by more chunks."""

    text: str


@dataclass(frozen=True)
class ActionEvent(Event):
    """The dispatcher produced an ``AgentAction`` for the current input."""

    action: AgentAction


@dataclass(frozen=True)
class ToolCall(Event):
    """A tool invocation request, ready for execution."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult(Event):
    """Result returned by a tool execution."""

    name: str
    output: str


@dataclass(frozen=True)
class Interrupt(Event):
    """The engine needs a user reply before it can continue."""

    type: Literal["choice", "text", "confirm"]
    prompt: str
    options: list[str] | None = None


@dataclass(frozen=True)
class Done(Event):
    """The engine finished the current turn for the given reason."""

    reason: DoneReason
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class ErrorEvent(Event):
    """An unrecoverable error occurred inside the engine.

    ``message`` is the human-readable summary that ``cli/main.py`` shows
    inline. ``traceback`` (added 2026-07-05 per arch-optimizer M4) carries
    the formatted stack trace when available; ``None`` for programmatic
    errors raised without going through the engine boundary (e.g. a
    pre-existing TestError fixture).
    """

    message: str
    traceback: str | None = None


__all__ = [
    "Event",
    "TextChunk",
    "ActionEvent",
    "ToolCall",
    "ToolResult",
    "Interrupt",
    "Done",
    "ErrorEvent",
    "DoneReason",
]
