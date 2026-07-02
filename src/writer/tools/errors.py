"""Error types raised by the tool layer.

Three tiers (per 备忘 07):
* ``ToolDeniedError`` — the runtime rejected the call (path traversal,
  shell disabled, dangerous command …).
* ``ToolNotFoundError`` — the registry has no tool with that name.
* ``ToolOutputTooLargeError`` — the tool produced something that would
  blow up the LLM context (rare today; reserved for future use).

All three derive from ``ToolError`` so callers can catch them uniformly.
"""

from __future__ import annotations


class ToolError(Exception):
    """Base class for every tool-layer failure."""


class ToolDeniedError(ToolError):
    """The runtime refused the operation (typically path / permission)."""


class ToolNotFoundError(ToolError):
    """The registry has no tool registered under this name."""


class ToolOutputTooLargeError(ToolError):
    """A tool produced output that exceeds safety thresholds."""


__all__ = [
    "ToolDeniedError",
    "ToolError",
    "ToolNotFoundError",
    "ToolOutputTooLargeError",
]
