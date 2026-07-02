"""Built-in writer tools (per 备忘 13).

This sub-package keeps individual tool implementations close to the
project root while the registry lives in ``writer.tools``. Add new
tools here and register them in ``built_tool_registry()``.
"""

from writer.tools.builtin.analysis_tools import Wordcount
from writer.tools.builtin.file_tools import SafeListDir, SafeReadFile
from writer.tools.builtin.foreshadow_tools import ForeshadowQuery
from writer.tools.builtin.locate_tools import ChapterLocate

__all__ = [
    "ChapterLocate",
    "ForeshadowQuery",
    "SafeListDir",
    "SafeReadFile",
    "Wordcount",
    "built_tool_registry",
]


def built_tool_registry() -> "writer.tools.registry.ToolRegistry":  # noqa: F821
    """Return a fresh ``ToolRegistry`` populated with every built-in tool."""

    from writer.tools.registry import ToolRegistry

    return ToolRegistry(
        tools=[
            SafeReadFile(),
            SafeListDir(),
            Wordcount(),
            ChapterLocate(),
            ForeshadowQuery(),
        ],
    )
