"""路由层 —— 把用户输入映射为结构化 :class:`AgentAction`。

公开 API 位于 :mod:`writer.routing.intent_router`；本包做浅层 re-export，
让调用方可以简单地 ``from writer.routing import IntentRouter``。
"""

from writer.routing.composite_router import CompositeRouter
from writer.routing.intent_router import (
    ActionType,
    AgentAction,
    IntentRouter,
    Role,
    RuleBasedIntentRouter,
)
from writer.routing.llm_router import LlmIntentRouter

__all__ = [
    "ActionType",
    "AgentAction",
    "CompositeRouter",
    "IntentRouter",
    "LlmIntentRouter",
    "Role",
    "RuleBasedIntentRouter",
]
