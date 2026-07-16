"""Runner 的事件数据类层次。

事件是 ``writer.runner`` 与其消费者（REPL、未来的 Engine、测试）之间的公共契约。
事件均为不可变结构，消费者可以放心地用 ``match`` 匹配而无需做防御性拷贝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from writer.routing import AgentAction


DoneReason = Literal[
    "answered",
    "command_pending",
    "tool_pending",
    "ask_user",
    "aborted",
    "tool_completed",
    "tool_loop_completed",
    "workflow_completed",
]


@dataclass(frozen=True)
class Event:
    """所有 runner 事件的基类。"""


@dataclass(frozen=True)
class TextChunk(Event):
    """一段人类可读文本，可能后跟更多文本块。"""

    text: str


@dataclass(frozen=True)
class ActionEvent(Event):
    """派发器已为当前输入产出 ``AgentAction``。"""

    action: AgentAction


@dataclass(frozen=True)
class ToolCall(Event):
    """工具调用请求，准备执行。"""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult(Event):
    """工具执行的返回结果。"""

    name: str
    output: str


@dataclass(frozen=True)
class Interrupt(Event):
    """Runner 在继续之前需要用户回复。"""

    type: Literal["choice", "text", "confirm"]
    prompt: str
    options: list[str] | None = None


@dataclass(frozen=True)
class Done(Event):
    """Runner 因指定原因结束当前轮次。"""

    reason: DoneReason
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class ErrorEvent(Event):
    """Runner 内部发生了不可恢复的错误。

    ``message`` 是 ``cli/main.py`` 内联展示的人类可读摘要；``traceback``
    （2026-07-05 按 arch-optimizer M4 增补）携带格式化的堆栈（若可用），
    未经过 Runner 边界（例如预先存在的 TestError fixture）抛出的程序化错误
    时为 ``None``。
    """

    message: str
    traceback: str | None = None


__all__ = [
    "Event",
    "TextChunk",
    "ActionEvent",
    "ToolCall",
    "ToolResult",
    "Interrupt",
    "Done",
    "ErrorEvent",
    "DoneReason",
]
