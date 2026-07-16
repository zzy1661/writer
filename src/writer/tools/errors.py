"""Tool 层抛出的错误类型。

五个层级（per 备忘 07；``ToolNotADirectoryError`` 与
``WorkflowNotFoundError`` 在 2026-07-05 增补，以让 builtin 工具与
工作流派发共用同一个异常层次）：
* ``ToolDeniedError`` —— runtime 拒绝了调用（路径穿越、shell 被
  禁用、危险命令…）。
* ``ToolNotFoundError`` —— registry 中没有该名称的工具。
* ``ToolNotADirectoryError`` —— 路径解析到了但不是目录。
* ``ToolOutputTooLargeError`` —— 工具产生了会把 LLM 上下文撑爆
  的输出（目前罕见；为未来保留）。
* ``WorkflowNotFoundError`` —— ``RunnerDeps.run_workflow`` 收到
  未知名称。

五者都派生自 ``ToolError``，调用方可以统一捕获；引擎 ``_engine_loop``
中现有的 ``except ToolError`` 分支仍然是暴露失败的唯一漏斗。
"""

from __future__ import annotations


class ToolError(Exception):
    """所有 tool 层失败的基类。"""


class ToolDeniedError(ToolError):
    """runtime 拒绝本次操作（通常是路径 / 权限）。"""


class ToolNotFoundError(ToolError):
    """registry 中没有以该名称注册的工具。"""


class ToolOutputTooLargeError(ToolError):
    """工具产生了超过安全阈值的输出。"""


class ToolNotADirectoryError(ToolError):
    """路径解析到了但不是目录（期望目录的位置是文件）。

    2026-07-05 增补，让所有 builtin 工具位于同一异常层次
    （per arch-optimizer M7）。在此之前，``SafeListDir`` 抛出 stdlib
    ``NotADirectoryError``，引擎 ``_engine_loop`` 中的 ``except ToolError``
    分支捕获不到。
    """


class WorkflowNotFoundError(ToolError):
    """``RunnerDeps.run_workflow`` 收到未知工作流名称。

    2026-07-05 增补，把未知工作流作为领域错误暴露（per arch-optimizer m18），
    而不是返回看起来像合法工作流块的占位字符串。
    """


__all__ = [
    "ToolDeniedError",
    "ToolError",
    "ToolNotADirectoryError",
    "ToolNotFoundError",
    "ToolOutputTooLargeError",
    "WorkflowNotFoundError",
]
