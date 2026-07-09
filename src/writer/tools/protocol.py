"""Tool 协议与结果类型。

``Tool`` 是一种无状态对象：可以注册一次并在多个会话中调用，
每次调用接收合适的 runtime。这让 ``ToolRegistry`` 构造廉价且
线程安全。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


@dataclass(frozen=True)
class ToolResult:
    """工具调用的结构化输出。

    ``output`` 是人类可读载荷（今天放进 ToolResult Event，将来喂给
    LangGraph state）；``truncated`` 记录 runtime 是否出于安全原因
    截断了输出；``metadata`` 携带结构化的辅助信息（计数、文件路径…）。
    """

    output: str
    truncated: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """无状态、感知 runtime 的能力。

    实现覆写 ``name``、``description`` 和 ``run``。Tool 绝不持有
    per-call 状态 —— 会话依赖 ``ToolRuntime``。
    """

    name: str
    description: str

    def run(self, runtime: ToolRuntime, **kwargs: Any) -> ToolResult:
        ...


__all__ = ["Tool", "ToolResult"]
