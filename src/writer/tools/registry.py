"""进程内 tool registry。

registry 是引擎 / LangGraph 能派发哪些工具的唯一真理来源。它在注册
时强制名称唯一，查找未命中时抛出 ``ToolNotFoundError``。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from writer.tools.errors import ToolNotFoundError
from writer.tools.langchain_bridge import _build_args_schema
from writer.tools.protocol import Tool, ToolResult
from writer.tools.runtime import ToolRuntime

if TYPE_CHECKING:
    from pydantic import BaseModel


class ToolRegistry:
    """按名称索引的工具集合。

    构造为空，然后逐个 ``.register()``，或通过构造函数一次性传入
    全部集合。重复名称抛 ``ValueError``，让配置错误在启动时就暴露，
    而不是在首次调用时。
    """

    def __init__(self, *, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> ToolRegistry:
        """按声明名称添加 ``tool``。可链式调用。"""
        if tool.name in self._tools:
            msg = f"工具重复注册: {tool.name!r}"
            raise ValueError(msg)
        self._tools[tool.name] = tool
        return self

    def unregister(self, name: str) -> None:
        """按名称移除一个工具。缺失名称静默忽略
        （缺失本身已是 registry 已被修改的证据）。"""

        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(f"未注册工具: {name!r}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def describe(self) -> list[ToolDescriptor]:
        """返回每个已注册工具元数据的快照。

        2026-07-08 为 LLM 驱动的工具循环增补：``LLMToolLoop`` 需要一个
        确定的、registry 视角的工具清单（包含哪些工具、各接受什么参数），
        而不必重新跑桥接（桥接会把 ``runtime`` 捕获进闭包）。args schema
        通过 :func:`writer.tools.langchain_bridge.to_langchain_tools` 使用的
        同一 ``_build_args_schema`` helper 派生，让两者保持同步。
        """

        return [
            ToolDescriptor(
                name=tool.name,
                description=tool.description,
                args_schema=_build_args_schema(tool),
            )
            for tool in self._tools.values()
        ]

    def invoke(
        self, name: str, runtime: ToolRuntime, /, **kwargs: object
    ) -> ToolResult:
        """解析并对 ``runtime`` 运行 ``name``。

        仅位置参数 ``runtime`` 让调用点保持明确
        （``registry.invoke("x", runtime, path="…")``）。
        """

        return self.get(name).run(runtime, **kwargs)


@dataclass(frozen=True)
class ToolDescriptor:
    """工具元数据的对外快照。

        由 :meth:`ToolRegistry.describe` 用于喂给 LLM 驱动的工具循环。
        ``args_schema`` 是 :func:`writer.tools.langchain_bridge.to_langchain_tools`
        会附加到 LangChain wrapper 的同一 Pydantic 模型，因此 schema 的
        字段名、默认值和类型与循环最终调用的版本一致。
    """

    name: str
    description: str
    args_schema: type[BaseModel] | None


__all__ = ["ToolDescriptor", "ToolRegistry"]
