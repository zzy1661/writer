"""Tool layer: registry, runtime, built-in tools, and LangChain bridge.

Public entry points:

* ``ToolRuntime`` / ``ToolRegistry`` / ``Tool`` / ``ToolResult`` — core
  data types consumed by the engine and (later) LangGraph.
* Built-in tool classes (``SafeReadFile`` etc.) — exposed for direct
  construction and testing.
* ``built_tool_registry()`` — registers every built-in tool; this is the
  default wiring used by tests and (eventually) the engine session.
* ``to_langchain_tools`` — adapter that exposes the same tools to the
  LangGraph ``ToolNode``.
"""

from writer.tools import builtin
from writer.tools.builtin import (
    ChapterLocate,
    ForeshadowSearch,
    ProjectSearch,
    SafeEditFile,
    SafeGlob,
    SafeListDir,
    SafeReadFile,
    SafeWriteFile,
    Wordcount,
    built_tool_registry,
)
from writer.tools.errors import (
    ToolDeniedError,
    ToolError,
    ToolNotADirectoryError,
    ToolNotFoundError,
    ToolOutputTooLargeError,
    WorkflowNotFoundError,
)
from writer.tools.langchain_bridge import to_langchain_tools
from writer.tools.protocol import Tool, ToolResult
from writer.tools.registry import ToolRegistry
from writer.tools.runtime import DEFAULT_WRITE_WHITELIST, ToolRuntime

__all__ = [
    "ChapterLocate",
    "DEFAULT_WRITE_WHITELIST",
    "ForeshadowSearch",
    "ProjectSearch",
    "SafeEditFile",
    "SafeGlob",
    "SafeListDir",
    "SafeReadFile",
    "SafeWriteFile",
    "Tool",
    "ToolDeniedError",
    "ToolError",
    "ToolNotADirectoryError",
    "ToolNotFoundError",
    "ToolOutputTooLargeError",
    "ToolRegistry",
    "ToolResult",
    "ToolRuntime",
    "Wordcount",
    "WorkflowNotFoundError",
    "builtin",
    "built_tool_registry",
    "to_langchain_tools",
]
