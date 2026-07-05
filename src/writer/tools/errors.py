"""Error types raised by the tool layer.

Five tiers (per 备忘 07; ``ToolNotADirectoryError`` and
``WorkflowNotFoundError`` added 2026-07-05 to keep builtin tools and
workflow dispatch on the same exception hierarchy):
* ``ToolDeniedError`` — the runtime rejected the call (path traversal,
  shell disabled, dangerous command …).
* ``ToolNotFoundError`` — the registry has no tool with that name.
* ``ToolNotADirectoryError`` — the path resolved but is not a directory.
* ``ToolOutputTooLargeError`` — the tool produced something that would
  blow up the LLM context (rare today; reserved for future use).
* ``WorkflowNotFoundError`` — ``EngineDeps.run_workflow`` got an unknown name.

All five derive from ``ToolError`` so callers can catch them uniformly
and the engine's existing ``except ToolError`` branch in ``_engine_loop``
remains the single funnel for surfacing failures.
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


class ToolNotADirectoryError(ToolError):
    """The path resolved but is not a directory (file where dir was expected).

    Added 2026-07-05 to keep all builtin tools on the same exception
    hierarchy (per arch-optimizer M7). Before this, ``SafeListDir`` raised
    stdlib ``NotADirectoryError``, which the engine's ``except ToolError``
    branch in ``_engine_loop`` could not catch.
    """


class WorkflowNotFoundError(ToolError):
    """``EngineDeps.run_workflow`` was called with an unknown workflow name.

    Added 2026-07-05 to surface unknown workflows as a domain error
    (per arch-optimizer m18) instead of returning a placeholder string
    that looked like a legitimate workflow chunk to the user.
    """


__all__ = [
    "ToolDeniedError",
    "ToolError",
    "ToolNotADirectoryError",
    "ToolNotFoundError",
    "ToolOutputTooLargeError",
    "WorkflowNotFoundError",
]
