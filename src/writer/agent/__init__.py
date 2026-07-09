"""Agent 编排 —— 向后兼容 shim（仅路由 re-export）。

原先的 ``writer.agent`` 包混了路由（``WriterCommandAgent``，现在
是 :class:`writer.routing.IntentRouter`）和角色能力（``NovelAgent`` ——
该别名已消失）。在重构之后（per 备忘 16 / 本次重构 Phase 1）：

* 路由位于 :mod:`writer.routing`。
* 角色曾经位于 :mod:`writer.roles`，但 ``chg-remove-roles``
  （2026-07-09）删除了该包 —— 唯一幸存的 Python-side 能力
  （``process_init_brief``）现在位于
  :mod:`writer.agents.capability`。
* 工作流位于 :mod:`writer.workflows`。
* 技能位于 :mod:`writer.skills`。
* Agent（``fea-agent-mirror`` 新增）位于 :mod:`writer.agents`。

本模块作为薄 re-export shim 保留，让遗留路由 import
（``from writer.agent import IntentRouter``）继续解析，同时让其余
代码库完成迁移。新代码应直接从新包 import。

``WriterCommandAgent`` 别名暂时保留（超出 ``fea-agent-mirror``
重命名范围；改动它会把变更扩散到 router 的协议表面）。
"""

from writer.routing import (
    ActionType,
    AgentAction,
    IntentRouter,
    Role,
    RuleBasedIntentRouter,
)

# 原规则派发器的向后兼容别名。超出 ``fea-agent-mirror`` 重命名
# 范围；为仍 import ``WriterCommandAgent`` 的外部代码保留。
# 调用方必须在 router 别名上使用 ``.route()``（而非 ``.decide()``）。
WriterCommandAgent = RuleBasedIntentRouter

__all__ = [
    "ActionType",
    "AgentAction",
    "IntentRouter",
    "Role",
    "RuleBasedIntentRouter",
    "WriterCommandAgent",
]
