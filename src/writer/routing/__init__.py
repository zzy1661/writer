"""Routing layer — maps user input to a structured :class:`AgentAction`.

Public surface lives in :mod:`writer.routing.intent_router`; this package
shallow re-exports it so callers can simply ``from writer.routing import
IntentRouter``.
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
