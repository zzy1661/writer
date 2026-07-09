"""Tool 层：registry、runtime、内置工具与 LangChain 桥接。

公开入口：

* ``ToolRuntime`` / ``ToolRegistry`` / ``Tool`` / ``ToolResult`` —
  引擎和（未来）LangGraph 消费的核心数据类型。
* 内置工具类（``SafeReadFile`` 等）—— 暴露给直接构造和测试。
* ``built_tool_registry()`` —— 注册所有内置工具；这是测试和
  （最终）engine session 使用的默认装配。
* ``to_langchain_tools`` —— 把同一套工具暴露给 LangGraph ``ToolNode``
  的适配器。
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
