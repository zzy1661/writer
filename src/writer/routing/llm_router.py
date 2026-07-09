"""LLM 支持的 :class:`IntentRouter` 实现。

把 LangChain 的 ``with_structured_output`` 接到 Pydantic
:class:`AgentAction` schema 上。Per 备忘 15，本路由器不能自己干
活 —— 它只把自然语言输入翻译成结构化 action；执行由引擎循环处理。

构造函数接受 :class:`writer.config.Settings` 并通过
:func:`writer.llm.get_llm` 构建自己的 LLM。测试通过次级构造函数
参数 ``llm=...`` 注入 fake LLM。

prompt 模板位于 :mod:`writer.prompts.router`；旧的 ``COMMAND_AGENT_PROMPT``
名字保留为 re-export，让现有调用方和测试可以继续使用。

Agent 派发（per ``fea-agent-mirror``）：
用 ``agent_registry=...`` 构造时，LLM system prompt 会包含一段
"可用 agent" 列表，来自 :meth:`AgentRegistry.descriptions` 的
``{name, description, genre}``。LLM 可以在返回的 :class:`AgentAction`
上设置 ``target_agent``，此时引擎循环会派发给所选 agent
（参见 :mod:`writer.engine.loop` 的 ``case "agent"``）。基于规则的
路由器忽略 ``agent_registry`` —— 规则只处理斜杠命令。
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

# 向后兼容别名 —— 旧代码从本模块导入 COMMAND_AGENT_PROMPT。
# 模板现在位于 writer.prompts.router。
COMMAND_AGENT_PROMPT = COMMAND_AGENT_TEMPLATE


def _render_agent_section(descriptions: list[dict[str, str]]) -> str:
    """渲染路由器 system prompt 中的 ``可用 agent`` 段落。

    ``descriptions`` 为空时返回空字符串，便于无条件追加该段落。
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
    """通过 LLM 把自然语言输入翻译为 :class:`AgentAction`。

    构造方式：
    - ``LlmIntentRouter(settings)`` — 生产装配，使用 :func:`get_llm`。
    - ``LlmIntentRouter(settings, llm=fake_chat_model)`` — 测试注入。
    - ``LlmIntentRouter(settings, chain=fake_runnable)`` — 测试注入，
      绕过 LangChain 的 ``with_structured_output``（某些 fake 不实现）。
    - ``LlmIntentRouter(settings, agent_registry=registry)`` — 在 system
      prompt 中启用 agent 派发；LLM 可设置 ``target_agent`` 委托给
      已注册 agent。
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
        # ``_agent_descriptions`` 是 registry 面向 LLM 的冻结视图；
        # 在构造时计算一次，避免每次 ``route()`` 调用都重新枚举 registry。
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
        # RunnableSequence.__or__ 是动态类型的；cast 让 mypy 满意。
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

        # 原生 ``with_structured_output`` 路径不允许我们往预先构造好的
        # ``PromptTemplate | structured_llm`` 链中拼接额外消息。
        # 因此改为手动格式化模板 + 追加 agent section + 直接调用
        # 结构化 LLM。这与链的行为重复，但这是新增段落而不重建链的
        # 唯一办法。
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
        # 针对 Pydantic 类的 with_structured_output 直接返回模型本身。
        if isinstance(result, AgentAction):
            return _normalize_action(result)
        # 防御性：某些 LangChain 版本返回 dict；强制转换。
        return _normalize_action(AgentAction.model_validate(result))


def _with_agent_section(
    base_messages: list, agent_section: str
) -> list:
    """返回 ``base_messages`` 并把 agent section 追加到第一条 system 消息。

    若不存在 system 消息，则在开头插入一条。section 为空时
    直接返回 ``base_messages``。
    """

    if not agent_section:
        return list(base_messages)

    messages = list(base_messages)
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "system":
            new_content = (message.content or "") + agent_section
            messages[index] = SystemMessage(content=new_content)
            return messages
    # 没有 system 消息 → 在开头插入一条。
    return [SystemMessage(content=agent_section), *messages]


def _normalize_action(action: AgentAction) -> AgentAction:
    """补齐 LLM 经常遗漏但引擎需要的确定性字段。

    同时规范化 ``fea-agent-mirror`` 引入的 ``kind`` / ``target_agent``
    形态：当 LLM 填了 ``target_agent`` 时，强制 ``kind="agent"`` 并清空
    ``command``，让引擎的 ``case "agent"`` 分支成为唯一通路。
    """

    updates: dict[str, Any] = {}

    # Agent 派发：若 LLM 选择了 agent，强制 kind="agent" 并清空
    # command（agent 分支忽略 command）。
    if action.target_agent:
        updates["kind"] = "agent"
        updates["command"] = None
    elif action.kind is None:
        # 防御性：schema 默认是 "command"；只在缺失时设置。
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
