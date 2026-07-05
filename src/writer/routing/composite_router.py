"""Composite router: rule-first with LLM fallback.

When :meth:`RuleBasedIntentRouter.looks_like_command` returns True, the
rule router's output is returned immediately (zero LLM cost). For
natural-language input, the LLM is invoked; if it raises any exception
the rule router's output is returned instead so a flaky LLM never
breaks the engine.
"""

from __future__ import annotations

from writer.routing.intent_router import (
    AgentAction,
    IntentRouter,
    RuleBasedIntentRouter,
)
from writer.routing.llm_router import LlmIntentRouter


class CompositeRouter(IntentRouter):
    """Rule-first router with an LLM fallback."""

    def __init__(
        self,
        primary: RuleBasedIntentRouter,
        fallback: LlmIntentRouter,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def primary(self) -> RuleBasedIntentRouter:
        return self._primary

    @property
    def fallback(self) -> LlmIntentRouter:
        return self._fallback

    def route(self, user_input: str, project_state: str) -> AgentAction:
        if RuleBasedIntentRouter.looks_like_command(user_input):
            return self._primary.route(user_input, project_state)

        try:
            return self._fallback.route(user_input, project_state)
        except Exception:  # noqa: BLE001 — fallback is best-effort
            return self._primary.route(user_input, project_state)


__all__ = ["CompositeRouter"]
