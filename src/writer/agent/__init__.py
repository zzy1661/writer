"""Agent orchestration — back-compat shim.

The previous ``writer.agent`` package mixed routing (``WriterCommandAgent``,
now :class:`writer.routing.IntentRouter`) with role capabilities
(``NovelAgent``, now :class:`writer.roles.StoryConsultant`). After the
refactor (per 备忘 16 / 本次重构 Phase 1):

* Routing lives in :mod:`writer.routing`.
* Roles live in :mod:`writer.roles`.
* Workflows live in :mod:`writer.workflows`.
* Skills (future) live in :mod:`writer.skills`.

This module remains as a thin re-export shim so legacy imports such as
``from writer.agent import NovelAgent`` continue to resolve while the rest
of the codebase is migrated. New code should import directly from the
new packages.
"""

from writer.roles import OutlineResult, StoryConsultant
from writer.routing import (
    ActionType,
    AgentAction,
    IntentRouter,
    Role,
    RuleBasedIntentRouter,
)

# Back-compat aliases.
# ``NovelAgent`` was the original facade exposed by ``writer.agent``; it is
# now the same class as ``StoryConsultant``. ``WriterCommandAgent`` was the
# original rule-based dispatcher; it is now the rule-based
# ``IntentRouter``. Callers must use ``.route()`` (not ``.decide()``) on the
# router alias.
NovelAgent = StoryConsultant
WriterCommandAgent = RuleBasedIntentRouter

__all__ = [
    "ActionType",
    "AgentAction",
    "IntentRouter",
    "NovelAgent",
    "OutlineResult",
    "Role",
    "RuleBasedIntentRouter",
    "StoryConsultant",
    "WriterCommandAgent",
]
