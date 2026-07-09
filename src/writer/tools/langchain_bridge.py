"""从 writer ``Tool`` 对象桥接到 LangChain ``BaseTool``。

当 LangGraph 的 ``ToolNode`` 到来时（per 04），它会期望一组
LangChain ``BaseTool`` 实例。本适配器按需产出它们，无需让每个
writer tool 同时也是 ``BaseTool`` 子类。

返回的工具在闭包中捕获 ``runtime``，因此单个 registry 可以
通过一次调用产出特定会话的 base tool。每个 wrapper 还会根据
writer tool 的 ``run`` 签名生成一个类型化的 ``args_schema``，
这是让 LangChain 把输入 dict 可靠地解包回 kwargs 的唯一稳妥办法。
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from writer.tools.runtime import ToolRuntime

if TYPE_CHECKING:
    from writer.tools.protocol import Tool
    from writer.tools.registry import ToolRegistry


def _build_args_schema(writer_tool: Tool) -> type[BaseModel] | None:
    """从 writer tool 的 ``run`` 签名派生一个 Pydantic v2 模型。

    跳过 ``self`` 和 ``runtime``（后者被桥接的闭包捕获）。其余
    keyword 参数都成为类型化字段；如果 writer 提供了默认值，
    默认值会被保留。
    """

    sig = inspect.signature(writer_tool.run)
    fields: dict[str, Any] = {}
    skip = {"self", "runtime"}

    for name, param in sig.parameters.items():
        if name in skip:
            continue
        if param.kind not in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            continue
        annotation = (
            param.annotation if param.annotation is not inspect.Parameter.empty else Any
        )
        default = (
            param.default if param.default is not inspect.Parameter.empty else ...
        )
        fields[name] = (annotation, Field(default=default))

    if not fields:
        return None
    return create_model(f"{writer_tool.name}_args", **fields)


def to_langchain_tools(
    registry: ToolRegistry, runtime: ToolRuntime
) -> list[BaseTool]:
    """把每个已注册的 writer tool 包装为 LangChain ``BaseTool``。

    返回的工具调用 writer ``Tool.run(runtime, **kwargs)`` 契约，并把
    ``ToolResult.output`` 暴露给 LangChain。结构化输出（``truncated``、
    ``metadata``）在此接缝处被丢弃 —— 它由 LangGraph state 单独
    记录（per 04）。
    """

    def _make(writer_tool: Tool) -> BaseTool:
        def _invoke(**kwargs: object) -> str:
            return writer_tool.run(runtime, **kwargs).output

        # ``__name__`` 对 LangChain 工具发现很重要，``__doc__`` 成为
        # 暴露给模型的工具描述。
        _invoke.__name__ = writer_tool.name
        _invoke.__doc__ = writer_tool.description

        args_schema = _build_args_schema(writer_tool)
        return StructuredTool.from_function(
            _invoke,
            name=writer_tool.name,
            description=writer_tool.description,
            args_schema=args_schema,
        )

    return [
        _make(registry.get(name)) for name in registry.names()
    ]


__all__ = ["to_langchain_tools"]
