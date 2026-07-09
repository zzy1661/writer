"""Skill 抛出的领域异常。

与 protocol 分开，让 skill 实现、引擎边界与消费者可以在不引入
较重的引擎事件类型的前提下 import 它们。与 :mod:`writer.tools.errors`
对称（引擎循环也会捕获 —— 见 :mod:`writer.engine.loop` 中的
``_engine_loop``）。
"""

from __future__ import annotations


class SkillError(Exception):
    """``Skill.run()`` 内部可恢复失败的基类。

    :func:`writer.engine.loop._engine_loop` 中的引擎边界会专门捕获
    本异常（在 ``ToolError`` 之后），把失败暴露为 ``ErrorEvent`` 后
    接 ``Done(reason='aborted')``，payload 为
    ``{'error': str(exc), 'command': <slash>}``，让 REPL 能渲染清爽
    的红色 ✗ 标记以及被拒绝的命令。

    Skill 应为任何用户可恢复的条件（缺失 project root、前置条件
    未满足、参数格式错误）抛 :class:`SkillError`（或其子类）。
    真正意外的 bug（实现内部的 ValueError / KeyError）原样冒泡，
    让引擎的 catch-all ``except Exception`` 分支仍然产出 ErrorEvent。
    """


__all__ = ["SkillError"]
