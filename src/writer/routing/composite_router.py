"""组合路由器：规则优先，LLM 兜底。

当 :meth:`RuleBasedIntentRouter.looks_like_command` 返回 True 时，
直接返回规则路由器的结果（零 LLM 成本）。对于自然语言输入，
调用 LLM；若抛出任何异常，则返回规则路由器的结果，让不稳定的
LLM 永远不会破坏引擎。

2026-07-05（arch-optimizer m6 / m13）：``primary`` / ``fallback`` 属性
的类型现在为 :class:`writer.routing.IntentRouter`（之前是具体
``RuleBasedIntentRouter`` / ``LlmIntentRouter``），让 API 表面不泄漏
具体类身份；回退路径在返回规则结果前会 log.warning，让不稳定的 LLM
在运维日志中可见。
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
    """规则优先的路由器，带 LLM 兜底。"""

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
        except Exception as exc:  # noqa: BLE001 — 兜底是尽力而为
            log.warning(
                "LLM router 失败,回退到 rule router: %r", exc, exc_info=True
            )
            return self._primary.route(user_input, project_state)


__all__ = ["CompositeRouter"]
