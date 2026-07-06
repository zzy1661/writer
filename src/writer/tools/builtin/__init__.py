"""Built-in writer tools (per 备忘 13).

This sub-package keeps individual tool implementations close to the
project root while the registry lives in ``writer.tools``. Add new
tools here and register them in ``built_tool_registry()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from writer.tools.builtin.analysis_tools import ProjectSearch, Wordcount
from writer.tools.builtin.file_tools import SafeListDir, SafeReadFile
from writer.tools.builtin.foreshadow_tools import ForeshadowQuery
from writer.tools.builtin.locate_tools import ChapterLocate
from writer.tools.protocol import Tool

if TYPE_CHECKING:
    from writer.tools.registry import ToolRegistry

__all__ = [
    "ChapterLocate",
    "ForeshadowQuery",
    "ProjectSearch",
    "SafeListDir",
    "SafeReadFile",
    "Wordcount",
    "built_tool_registry",
]


def built_tool_registry() -> ToolRegistry:
    """Return a fresh ``ToolRegistry`` populated with every built-in tool."""

    from writer.tools.registry import ToolRegistry as _ToolRegistry

    # Implementations use named keyword-only parameters (per 备忘 13: needed
    # for LangChain ``StructuredTool.args_schema`` to introspect the
    # signature), which mypy's strict mode treats as a *narrower* call
    # surface than the Protocol's ``**kwargs: Any``. The cast is safe —
    # ``Tool`` is ``@runtime_checkable`` and the registry validates names
    # at construction time.
    return _ToolRegistry(
        tools=cast(
            list[Tool],
            [
                SafeReadFile(),
                SafeListDir(),
                Wordcount(),
                ProjectSearch(),
                ChapterLocate(),
                ForeshadowQuery(),
            ],
        ),
    )
