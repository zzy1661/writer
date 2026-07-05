"""LLM-backed :class:`IntentRouter` implementation.

Wires LangChain's ``with_structured_output`` to a Pydantic
:class:`AgentAction` schema. Per 备忘 15, this router must NOT do work
itself — it only translates natural-language input into a structured
action; the engine loop handles execution.

The constructor takes :class:`writer.config.Settings` and builds its own
LLM via :func:`writer.llm.get_llm`. Tests inject a fake ``llm`` via the
secondary constructor argument ``llm=...``.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from writer.config import Settings
from writer.llm import get_llm
from writer.routing.intent_router import AgentAction, IntentRouter

COMMAND_AGENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是 Writer Agent 的前台调度 Agent。\n"
                "职责:把用户输入转成 AgentAction,不要直接动手。\n"
                "边界:\n"
                "- 不直接写文件。\n"
                "- 不直接生成整章正文。\n"
                "- 不直接修改 AGENT.md。\n"
                "- 长任务(整章写作、章节审核) → start_workflow。\n"
                "- 轻量查询(伏笔、字数、定位) → call_tool。\n"
                "- 信息不足 → ask_user。\n"
                "- 明确命令或闲聊 → answer_directly。\n"
            ),
        ),
        (
            "human",
            "项目状态: {project_state}\n用户输入: {user_input}\n",
        ),
    ]
)


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
        if chain is not None:
            self._chain: Runnable = chain
            return
        if llm is None:
            llm = get_llm(settings)
        structured_llm = llm.with_structured_output(AgentAction)  # type: ignore[arg-type]
        # RunnableSequence.__or__ is dynamically typed; cast keeps mypy happy.
        self._chain = COMMAND_AGENT_PROMPT | structured_llm  # type: ignore[assignment,operator]

    def route(self, user_input: str, project_state: str) -> AgentAction:
        result: Any = self._chain.invoke(
            {"user_input": user_input, "project_state": project_state}
        )
        # with_structured_output against a Pydantic class returns the model itself.
        if isinstance(result, AgentAction):
            return result
        # Defensive: some LangChain versions return a dict; coerce.
        return AgentAction.model_validate(result)


__all__ = ["COMMAND_AGENT_PROMPT", "LlmIntentRouter"]
