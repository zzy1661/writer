"""Composite router: rule-first with LLM fallback.

When :meth:`RuleBasedIntentRouter.looks_like_command` returns True, the
rule router's output is returned immediately (zero LLM cost). For
natural-language input, the LLM is invoked; if it raises any exception
the rule router's output is returned instead so a flaky LLM never
breaks the engine.

2026-07-05 (arch-optimizer m6 / m13): the ``primary`` / ``fallback``
properties now type as :class:`writer.routing.IntentRouter` (was
concrete ``RuleBasedIntentRouter`` / ``LlmIntentRouter``) so the API
surface doesn't leak concrete-class identity, and the fallback path
logs a warning before returning the rule result so flaky LLM is
visible in the operator's logs.
"""

from __future__ import annotations

import logging

from writer.routing.intent_router import (
    AgentAction,
    IntentRouter,
    RuleBasedIntentRouter,
)

log = logging.getLogger(__name__)


class CompositeRouter(IntentRouter):
    """Rule-first router with an LLM fallback."""

    def __init__(
        self,
        primary: IntentRouter,
        fallback: IntentRouter,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def primary(self) -> IntentRouter:
        return self._primary

    @property
    def fallback(self) -> IntentRouter:
        return self._fallback

    def route(self, user_input: str, project_state: str) -> AgentAction:
        if RuleBasedIntentRouter.looks_like_command(user_input):
            return self._primary.route(user_input, project_state)

        try:
            return self._fallback.route(user_input, project_state)
        except Exception as exc:  # noqa: BLE001 — fallback is best-effort
            log.warning(
                "LLM router 失败,回退到 rule router: %r", exc, exc_info=True
            )
            return self._primary.route(user_input, project_state)


__all__ = ["CompositeRouter"]
