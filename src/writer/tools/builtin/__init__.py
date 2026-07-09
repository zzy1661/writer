"""内置 writer 工具（per 备忘 13）。

本子包让单个工具实现贴近项目根目录，而 registry 位于
``writer.tools`` 中。新增工具请在此加入并在
``built_tool_registry()`` 中注册。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from writer.tools.builtin.analysis_tools import ProjectSearch, Wordcount
from writer.tools.builtin.file_tools import (
    SafeEditFile,
    SafeListDir,
    SafeReadFile,
    SafeWriteFile,
)
from writer.tools.builtin.foreshadow_tools import ForeshadowSearch
from writer.tools.builtin.glob_tools import SafeGlob
from writer.tools.builtin.locate_tools import ChapterLocate
from writer.tools.protocol import Tool

if TYPE_CHECKING:
    from writer.tools.registry import ToolRegistry

__all__ = [
    "ChapterLocate",
    "ForeshadowSearch",
    "ProjectSearch",
    "SafeEditFile",
    "SafeGlob",
    "SafeListDir",
    "SafeReadFile",
    "SafeWriteFile",
    "Wordcount",
    "built_tool_registry",
]


def built_tool_registry() -> ToolRegistry:
    """返回一个填充了所有内置工具的新 ``ToolRegistry``。"""

    from writer.tools.registry import ToolRegistry as _ToolRegistry

    # 实现使用命名 keyword-only 参数（per 备忘 13：LangChain
    # ``StructuredTool.args_schema`` 需要通过 introspection 读取签名），
    # mypy 的 strict 模式把这视为比 Protocol 的 ``**kwargs: Any`` 更窄的
    # 调用表面。cast 是安全的 —— ``Tool`` 是 ``@runtime_checkable``，
    # registry 在构造时校验名称。
    return _ToolRegistry(
        tools=cast(
            list[Tool],
            [
                SafeReadFile(),
                SafeListDir(),
                SafeWriteFile(),
                SafeEditFile(),
                SafeGlob(),
                Wordcount(),
                ProjectSearch(),
                ChapterLocate(),
                ForeshadowSearch(),
            ],
        ),
    )
