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

Agent dispatch (per ``fea-agent-mirror``):
When constructed with ``agent_registry=...`` the LLM system prompt
includes a "可用 agent" section listing each agent's ``{name, description,
genre}`` from :meth:`AgentRegistry.descriptions`. The LLM is then free
to set ``target_agent`` on the returned :class:`AgentAction`, in which
case the engine loop will dispatch to the chosen agent (see
:mod:`writer.engine.loop` ``case "agent"``). The rule-based router
ignores ``agent_registry`` — rules operate on slash commands only.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import Runnable

from writer.config import Settings
from writer.llm import get_llm
from writer.llm.structured import (
    invoke_structured_json,
    needs_json_prompt_structured_output,
)
from writer.prompts.router import COMMAND_AGENT_TEMPLATE
from writer.routing.intent_router import AgentAction, IntentRouter

if TYPE_CHECKING:
    from writer.agents import AgentRegistry

log = logging.getLogger(__name__)

# Backward-compatible alias — earlier code imported COMMAND_AGENT_PROMPT
# from this module. The template now lives in writer.prompts.router.
COMMAND_AGENT_PROMPT = COMMAND_AGENT_TEMPLATE


def _render_agent_section(descriptions: list[dict[str, str]]) -> str:
    """Render the ``可用 agent`` section for the router system prompt.

    Returns an empty string when ``descriptions`` is empty so the
    section can be unconditionally appended.
    """

    if not descriptions:
        return ""

    lines = [
        "",
        "## 可用 agent（按 description 自行决定派给谁；命中斜杠命令时优先走 command）",
        "",
    ]
    for entry in descriptions:
        name = entry["name"]
        description = entry["description"]
        genre = entry["genre"]
        lines.append(f"- name={name!r} genre={genre!r}: {description}")
    lines.extend(
        [
            "",
            "如果你的判断是「这个请求更适合某个 agent 处理」→ 把 AgentAction 的 "
            "`kind` 设为 'agent'，把 `target_agent` 设为该 agent 的 name，并把 "
            "`command` 留空。",
            "否则 → 走原本的 command / call_tool / start_workflow / ask_user / "
            "answer_directly 路径，`kind` 保持 'command'（默认）。",
        ]
    )
    return "\n".join(lines)


class LlmIntentRouter(IntentRouter):
    """Translate natural-language input to :class:`AgentAction` via an LLM.

    Construct via:
    - ``LlmIntentRouter(settings)`` — production wiring; uses :func:`get_llm`.
    - ``LlmIntentRouter(settings, llm=fake_chat_model)`` — test injection.
    - ``LlmIntentRouter(settings, chain=fake_runnable)`` — test injection
      bypassing LangChain's ``with_structured_output`` (which some fakes
      do not implement).
    - ``LlmIntentRouter(settings, agent_registry=registry)`` — enables
      agent dispatch in the system prompt; the LLM may set
      ``target_agent`` to delegate to a registered agent.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        llm: BaseChatModel | None = None,
        chain: Runnable | None = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self._chain: Runnable | None = None
        self._llm: BaseChatModel | None = None
        self._use_json_prompt = False
        # ``_agent_descriptions`` is the frozen LLM-facing view of the
        # registry; computed once at construction so each ``route()``
        # call doesn't re-enumerate the registry.
        self._agent_descriptions: list[dict[str, str]] = []
        if agent_registry is not None:
            self._agent_descriptions = list(agent_registry.descriptions())
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
        agent_section = _render_agent_section(self._agent_descriptions)

        if self._use_json_prompt:
            if self._llm is None:
                msg = "JSON prompt structured route requires an LLM"
                raise ValueError(msg)
            base_messages = COMMAND_AGENT_PROMPT.invoke(
                {"user_input": user_input, "project_state": project_state}
            ).to_messages()
            messages = _with_agent_section(base_messages, agent_section)
            return _normalize_action(
                invoke_structured_json(self._llm, messages, AgentAction)
            )

        if self._chain is None:
            msg = "LlmIntentRouter has neither chain nor LLM"
            raise ValueError(msg)

        # The native ``with_structured_output`` path does not let us
        # splice extra messages into a pre-built ``PromptTemplate |
        # structured_llm`` chain. So we fall back to formatting the
        # template manually + appending the agent section + invoking
        # the structured LLM directly. This duplicates the chain's
        # behaviour but is the only way to add the section without
        # rebuilding the chain.
        structured_llm = (
            self._chain.last
            if hasattr(self._chain, "last")
            else self._chain
        )
        base_messages = COMMAND_AGENT_PROMPT.invoke(
            {"user_input": user_input, "project_state": project_state}
        ).to_messages()
        messages = _with_agent_section(base_messages, agent_section)
        result: Any = structured_llm.invoke(messages)
        # with_structured_output against a Pydantic class returns the
        # model itself.
        if isinstance(result, AgentAction):
            return _normalize_action(result)
        # Defensive: some LangChain versions return a dict; coerce.
        return _normalize_action(AgentAction.model_validate(result))


def _with_agent_section(
    base_messages: list, agent_section: str
) -> list:
    """Return ``base_messages`` with the agent section appended to the
    first system message.

    If no system message is present, prepends one. The section is
    empty → ``base_messages`` is returned unchanged.
    """

    if not agent_section:
        return list(base_messages)

    messages = list(base_messages)
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "system":
            new_content = (message.content or "") + agent_section
            messages[index] = SystemMessage(content=new_content)
            return messages
    # No system message → prepend a new one.
    return [SystemMessage(content=agent_section), *messages]


def _normalize_action(action: AgentAction) -> AgentAction:
    """Fill deterministic fields that LLMs often omit but the engine needs.

    Also normalizes the new ``kind`` / ``target_agent`` shape (per
    ``fea-agent-mirror``): when the LLM fills in ``target_agent``, force
    ``kind="agent"`` and clear ``command`` so the engine's
    ``case "agent"`` branch is the only path.
    """

    updates: dict[str, Any] = {}

    # Agent dispatch: if the LLM picked an agent, force kind="agent"
    # and clear command (the agent branch ignores command).
    if action.target_agent:
        updates["kind"] = "agent"
        updates["command"] = None
    elif action.kind is None:
        # Defensive: schema default is "command"; only set when missing.
        updates["kind"] = "command"

    if action.workflow == "write_chapter":
        updates.setdefault("command", action.command or "/创作")
        updates.setdefault("role", action.role or "story_agent")
    elif action.workflow == "review_chapter":
        updates.setdefault("command", action.command or "/审核")
        updates.setdefault("role", action.role or "reviewer")
    elif action.tool_name in {"safe_read_file", "safe_list_dir"}:
        updates.setdefault("command", action.command or "")
        updates.setdefault("role", action.role or "story_agent")
    elif action.tool_name == "wordcount":
        updates.setdefault("command", action.command or "/字数统计")
        updates.setdefault("role", action.role or "story_agent")
    elif action.tool_name == "foreshadow_search":
        updates.setdefault("role", action.role or "story_agent")

    return action.model_copy(update=updates) if updates else action


__all__ = ["COMMAND_AGENT_PROMPT", "LlmIntentRouter"]
