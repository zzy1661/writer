"""Agent orchestration — back-compat shim (routing re-exports only).

The previous ``writer.agent`` package mixed routing (``WriterCommandAgent``,
now :class:`writer.routing.IntentRouter`) with role capabilities
(``NovelAgent`` — that alias is gone). After the refactor (per 备忘 16 /
本次重构 Phase 1):

* Routing lives in :mod:`writer.routing`.
* Roles lived in :mod:`writer.roles` until ``chg-remove-roles``
  (2026-07-09) deleted the package — the only Python-side capability
  that survived (``process_init_brief``) now lives in
  :mod:`writer.agents.capability`.
* Workflows live in :mod:`writer.workflows`.
* Skills live in :mod:`writer.skills`.
* Agents (new per ``fea-agent-mirror``) live in :mod:`writer.agents`.

This module remains as a thin re-export shim so legacy routing imports
(``from writer.agent import IntentRouter``) continue to resolve while
the rest of the codebase is migrated. New code should import directly
from the new packages.

The ``WriterCommandAgent`` alias is kept for now (out of scope for the
``fea-agent-mirror`` rename; touching it would expand the change into
the router's protocol surface).
"""

from writer.routing import (
    ActionType,
    AgentAction,
    IntentRouter,
    Role,
    RuleBasedIntentRouter,
)

# Back-compat alias for the original rule-based dispatcher. Out of scope
# for the ``fea-agent-mirror`` rename; preserved for any external code
# that still imports ``WriterCommandAgent``. Callers must use
# ``.route()`` (not ``.decide()``) on the router alias.
WriterCommandAgent = RuleBasedIntentRouter

__all__ = [
    "ActionType",
    "AgentAction",
    "IntentRouter",
    "Role",
    "RuleBasedIntentRouter",
    "WriterCommandAgent",
]
