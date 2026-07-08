"""LLM-backed :class:`IntentRouter` implementation.

Wires LangChain's ``with_structured_output`` to a Pydantic
:class:`AgentAction` schema. Per 备忘 15, this router must NOT do work
itself — it only translates natural-language input into a structured
action; the engine loop handles execution.

The constructor takes :class:`writer.config.Settings` and builds its own
LLM via :func:`writer.llm.get_llm`. Tests inject a fake ``llm`` via the
secondary constructor argument ``llm=...``.

The prompt template lives in :mod:`writer.prompts.router`; the legacy
``COMMAND_AGENT_PROMPT`` name is preserved as a re-export so existing
callers and tests can keep using it.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from writer.config import Settings
from writer.llm import get_llm
from writer.llm.structured import (
    invoke_structured_json,
    needs_json_prompt_structured_output,
)
from writer.prompts.router import COMMAND_AGENT_TEMPLATE
from writer.routing.intent_router import AgentAction, IntentRouter

# Backward-compatible alias — earlier code imported COMMAND_AGENT_PROMPT
# from this module. The template now lives in writer.prompts.router.
COMMAND_AGENT_PROMPT = COMMAND_AGENT_TEMPLATE


class LlmIntentRouter(IntentRouter):
    """Translate natural-language input to :class:`AgentAction` via an LLM.

    Construct via:
    - ``LlmIntentRouter(settings)`` — production wiring; uses :func:`get_llm`.
    - ``LlmIntentRouter(settings, llm=fake_chat_model)`` — test injection.
    - ``LlmIntentRouter(settings, chain=fake_runnable)`` — test injection
      bypassing LangChain's ``with_structured_output`` (which some fakes
      do not implement).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        llm: BaseChatModel | None = None,
        chain: Runnable | None = None,
    ) -> None:
        self._chain: Runnable | None = None
        self._llm: BaseChatModel | None = None
        self._use_json_prompt = False
        if chain is not None:
            self._chain = chain
            return
        if llm is None:
            llm = get_llm(settings)
        if needs_json_prompt_structured_output(settings):
            self._llm = llm
            self._use_json_prompt = True
            return
        structured_llm = llm.with_structured_output(AgentAction)  # type: ignore[arg-type]
        # RunnableSequence.__or__ is dynamically typed; cast keeps mypy happy.
        self._chain = COMMAND_AGENT_PROMPT | structured_llm  # type: ignore[assignment,operator]

    def route(self, user_input: str, project_state: str) -> AgentAction:
        if self._use_json_prompt:
            if self._llm is None:
                msg = "JSON prompt structured route requires an LLM"
                raise ValueError(msg)
            messages = COMMAND_AGENT_PROMPT.invoke(
                {"user_input": user_input, "project_state": project_state}
            ).to_messages()
            return _normalize_action(
                invoke_structured_json(self._llm, messages, AgentAction)
            )

        if self._chain is None:
            msg = "LlmIntentRouter has neither chain nor LLM"
            raise ValueError(msg)
        result: Any = self._chain.invoke(
            {"user_input": user_input, "project_state": project_state}
        )
        # with_structured_output against a Pydantic class returns the model itself.
        if isinstance(result, AgentAction):
            return _normalize_action(result)
        # Defensive: some LangChain versions return a dict; coerce.
        return _normalize_action(AgentAction.model_validate(result))


def _normalize_action(action: AgentAction) -> AgentAction:
    """Fill deterministic fields that LLMs often omit but the engine needs."""

    updates: dict[str, Any] = {}
    if action.workflow == "write_chapter":
        updates.setdefault("command", action.command or "/创作")
        updates.setdefault("role", action.role or "story_consultant")
    elif action.workflow == "review_chapter":
        updates.setdefault("command", action.command or "/审核")
        updates.setdefault("role", action.role or "reviewer")
    elif action.tool_name in {"safe_read_file", "safe_list_dir"}:
        updates.setdefault("command", action.command or "/查看")
        updates.setdefault("role", action.role or "story_consultant")
    elif action.tool_name == "project_search":
        updates.setdefault("command", action.command or "/搜索")
        updates.setdefault("role", action.role or "story_consultant")
    elif action.tool_name == "wordcount":
        updates.setdefault("command", action.command or "/字数统计")
        updates.setdefault("role", action.role or "story_consultant")
    elif action.tool_name == "foreshadow_search":
        updates.setdefault("role", action.role or "story_consultant")

    return action.model_copy(update=updates) if updates else action


__all__ = ["COMMAND_AGENT_PROMPT", "LlmIntentRouter"]
