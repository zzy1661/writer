"""Event data class hierarchy for the agent engine.

Events are the public contract between ``writer.engine`` and its consumers
(REPL, future EngineSession, tests). They are immutable so consumers can
freely ``match`` on them without defensive copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from writer.agent.command_agent import AgentAction


DoneReason = Literal[
    "answered",
    "command_pending",
    "tool_pending",
    "workflow_pending",
    "ask_user",
    "aborted",
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

    action: "AgentAction"


@dataclass(frozen=True)
class ToolCall(Event):
    """A tool invocation request, ready for execution."""

    name: str
    arguments: dict


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
    payload: dict | None = None


@dataclass(frozen=True)
class ErrorEvent(Event):
    """An unrecoverable error occurred inside the engine."""

    message: str


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
