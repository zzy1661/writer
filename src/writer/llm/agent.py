"""LLM 驱动的多步工具循环（ReAct 风格）。

``LlmIntentRouter`` 是单次翻译器：LLM 看到用户输入，产出单个
``AgentAction``，然后退出。这对路由而言没问题，但意味着模型永远
看不到它刚调用的工具的结果，所以像「搜一下玉佩，再告诉我它在第几章」
这样的多跳查询必须拆成两轮 REPL。

:mod:`writer.llm.agent` 把引擎的工具调用从外层状态机提到一个
ReAct 风格的循环里：

* 每一步都带着完整对话（system prompt + 工具目录 + 历史工具结果）
  调用 LLM。
* 模型要么产出 ``answer_directly`` 类型的 ``AgentAction``（循环结束），
  要么产出 ``call_tool``（循环通过 :class:`writer.tools.ToolRegistry`
  调用工具，往历史里追加 ``ToolMessage``，再次询问模型）。
* 硬性 ``MAX_LOOP_STEPS`` 预算限制工具调用次数，让病态模型无法
  无限循环。当预算耗尽时，循环产出兜底 ``TextChunk`` 总结最后一次
  工具输出，并以 ``Done(tool_loop_completed)`` 终止。

循环与引擎状态机是分离的关注 —— 引擎仍持有每轮上下文、REPL 路由
和外层 ``Done`` 事件。循环仅在路由的首个 action 是 ``call_tool``
且 engine deps 上配置了 ``tool_loop`` 时，由 ``engine.loop`` *委托*
给 —— 规则优先派发和非 LLM 的 ``_run_tool`` 路径保持不变。

分层：本模块位于 ``writer.llm``（而非 ``writer.engine``），让 engine
包从不直接 import LLM 类型。``EngineDeps`` 持有一个
``Optional[LLMToolLoop]`` 引用；当引擎想要循环时
``await deps.tool_loop.run(...)`` 并原样转发产出事件。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

from writer.config import Settings
from writer.engine.events import (
    Done,
    TextChunk,
    ToolCall,
    ToolResult,
)
from writer.llm.provider import get_llm
from writer.llm.structured import (
    invoke_structured_json,
    needs_json_prompt_structured_output,
)
from writer.routing.intent_router import AgentAction
from writer.tools.langchain_bridge import to_langchain_tools
from writer.tools.protocol import ToolResult as ProtocolToolResult
from writer.tools.registry import ToolDescriptor, ToolRegistry
from writer.tools.runtime import ToolRuntime

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps

# 每次轮次工具调用的硬上限。真正 ReAct agent 可以快速积累有用的
# 上下文；但失控的模型一直调用同一工具几乎总是坏掉或幻觉。5 对
# 「search → locate」链而言足够慷慨，同时保持最坏情况下的 token
# 消耗可预测。
MAX_LOOP_STEPS = 5


@dataclass
class ToolLoopState:
    """LLM 工具循环的每轮状态。

    生命周期为单轮：引擎每次委托给 ``LLMToolLoop.run`` 时构造一份
    全新状态。跨轮记忆属于 ``EngineSession``（按计划刻意排除在外）。

    Attributes:
        messages: LangChain 消息历史。起始是循环的 system prompt +
            用户输入的人类轮次，循环中累积 ``AIMessage`` /
            ``ToolMessage`` 对。
        tool_calls_made: 每次成功工具调用后递增的计数器。驱动预算
            校验。
        last_tool_result: 循环产出的最近一个 :class:`writer.tools.ToolResult`。
            预算耗尽时用于兜底 ``TextChunk`` 与 ``Done`` payload。
    """

    messages: list[BaseMessage] = field(default_factory=list)
    tool_calls_made: int = 0
    last_tool_result: ProtocolToolResult | None = None


class LLMToolLoop:
    """驱动 LLM 完成多步工具调用直至给出答案。

    支持两条 provider 路径，镜像 :class:`writer.routing.LlmIntentRouter`：

    * **原生结构化输出** —— ``llm.bind_tools(...)`` 用于尊重请求中
      ``tools`` 字段的 OpenAI 兼容 provider。模型产出 ``AIMessage`` 对象，
      其 ``tool_calls`` 属性携带结构化调用。
    * **JSON-prompt 结构化输出** —— 像 DeepSeek 这样的 provider 会拒绝
      原生 tool-binding payload，于是工具目录被序列化进 system prompt，
      模型产出 JSON 形式的 ``AgentAction``。
      :func:`writer.llm.structured.invoke_structured_json` 用 router
      用的同一 Pydantic schema 校验 payload。

    构造：

    * ``LLMToolLoop(settings, registry, runtime)`` —— 生产装配，通过
      :func:`writer.llm.provider.get_llm`。
    * ``LLMToolLoop(..., llm=fake_chat_model)`` —— 测试注入；绕过
      :func:`get_llm`。
    * ``LLMToolLoop(..., langchain_tools=[...])`` —— 测试注入；绕过
      ``to_langchain_tools``（它会在 ``runtime`` 上构建闭包）。当测试
      想观察循环如何处理 tool 消息而无需真实 registry 装配时很有用。
    """

    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        runtime: ToolRuntime,
        *,
        llm: BaseChatModel | None = None,
        langchain_tools: list[BaseTool] | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._runtime = runtime
        self._descriptors: list[ToolDescriptor] = list(registry.describe())
        self._use_json_prompt = needs_json_prompt_structured_output(settings)
        self._llm: BaseChatModel | None = llm or get_llm(settings)
        # 原生 tool binding：一次性构建，让每一步复用同一工具列表。
        # JSON-prompt provider 也构建该列表（为未来使用），但循环路径
        # 直接使用 descriptors。
        self._tools: list[BaseTool] = (
            langchain_tools
            if langchain_tools is not None
            else to_langchain_tools(registry, runtime)
        )
        self._bound_llm: Any = (
            self._llm.bind_tools(self._tools) if not self._use_json_prompt else None
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def runtime(self) -> ToolRuntime:
        return self._runtime

    @property
    def descriptors(self) -> Sequence[ToolDescriptor]:
        return self._descriptors

    async def run(
        self,
        action: AgentAction,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
        """驱动 ReAct 循环直至 ``answer_directly`` 或预算耗尽。

        ``action`` 是本轮路由的首个 ``call_tool`` 决策。我们用它为对话
        历史播种（让模型知道用户问的是什么，即便它的首个 action 是
        工具调用而非文本回答）。``ctx`` 通过 ``EngineContext.user_input``
        携带原始用户输入。

        工具调用抛出的异常向外传播 —— 引擎外层的 ``except ToolError``
        边界是暴露工具失败的唯一漏斗；我们不在这里吞异常，让相同的
        ``ErrorEvent + Done(aborted)`` UX 生效。

        ``deps`` 用于 :meth:`_initial_messages` 拼接 directive body 与
        agent identity —— 让 LLM 看到 SKILL.md / agent Markdown 提供的
        上下文（per Bug 02 修复）。
        """

        del cfg  # 当前未使用；为未来 per-loop 配置保留

        state = ToolLoopState(
            messages=self._initial_messages(action, ctx.user_input, deps=deps),
        )

        while state.tool_calls_made < MAX_LOOP_STEPS:
            ai_message = await self._invoke_model(state.messages)
            state.messages.append(ai_message)

            parsed = self._parse_ai_message(ai_message)
            if parsed is None:
                # 模型没产出可执行动作（无 tool_calls，也无法解析 JSON）。
                # 视为软失败：产出兜底回答并停止循环。
                yield TextChunk(
                    text="LLM 未产出可执行动作(无 tool_calls 且无法解析 JSON)。"
                )
                yield Done(
                    reason="tool_loop_completed",
                    payload={
                        "tool_calls_made": state.tool_calls_made,
                        "fallback": "no_action",
                    },
                )
                return

            if parsed.action_type == "answer_directly":
                yield TextChunk(text=parsed.answer or "")
                yield Done(
                    reason="answered",
                    payload={
                        "answer": parsed.answer,
                        "tool_calls_made": state.tool_calls_made,
                    },
                )
                return

            # parsed.action_type == "call_tool"
            tool_name = parsed.tool_name or ""
            arguments = dict(parsed.arguments)
            yield ToolCall(name=tool_name, arguments=arguments)

            # 故意让 ToolError 向外传播，让引擎外层 ``except ToolError``
            # 边界产出与规则优先路径一致的 ErrorEvent + Done(aborted)。
            result = self._registry.invoke(
                tool_name, self._runtime, **arguments
            )
            state.last_tool_result = result
            state.messages.append(
                self._build_tool_message(ai_message, tool_name, result.output)
            )
            yield ToolResult(name=tool_name, output=result.output)
            state.tool_calls_made += 1

        # 预算耗尽。产出兜底块，把最后一次工具返回的内容展示出来，
        # 让用户能基于它行动；然后以非错误 Done reason 终止 ——
        # 达到预算是*优雅*状态，不是失败。
        fallback_text = self._budget_fallback(state)
        yield TextChunk(text=fallback_text)
        yield Done(
            reason="tool_loop_completed",
            payload={
                "tool_calls_made": state.tool_calls_made,
                "last_output": (
                    state.last_tool_result.output
                    if state.last_tool_result is not None
                    else ""
                ),
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _initial_messages(
        self, action: AgentAction, user_input: str, *, deps: EngineDeps
    ) -> list[BaseMessage]:
        """用 system prompt + directive / agent body + 用户轮次为对话播种。

        System prompt 由四段拼接（per Bug 02 修复）:

        1. **base system prompt** —— 工具循环说明 + 工具目录；
        2. **directive body** —— 当 ``action.command`` 命中
           ``deps.directive_registry`` 时，追加 SKILL.md body + references；
        3. **agent identity** —— 当 ``action.target_agent`` 命中
           ``deps.agent_registry`` 时，追加 agent Markdown body；
        4. **router hint** —— 当 ``action.answer`` 非空时，追加
           router 拼好的 prompt hint（向后兼容）。
        """

        system_parts: list[str] = [self._system_prompt()]

        # 1. directive body:仅当 action 是 answer_directly 且有 command
        if action.action_type == "answer_directly" and action.command:
            directive_meta = deps.directive_registry.get(action.command)
            if directive_meta is not None:
                refs = "\n\n".join(
                    f"--- {relpath} ---\n{body}"
                    for relpath, body in directive_meta.references.items()
                )
                section = (
                    f"[directive body: {directive_meta.command}]\n"
                    f"{directive_meta.body}"
                )
                if refs:
                    section += f"\n\n[directive references]\n{refs}"
                system_parts.append(section)

        # 2. agent identity:仅当 action.target_agent 非空
        if action.target_agent:
            agent_meta = deps.agent_registry.get(action.target_agent)
            if agent_meta is not None:
                system_parts.append(
                    f"[agent identity: {agent_meta.name}]\n{agent_meta.body}"
                )

        # 3. router 拼好的 answer(用作 hint,不是指令)
        if action.answer:
            system_parts.append(f"[router hint]\n{action.answer}")

        return [
            SystemMessage(content="\n\n".join(system_parts)),
            HumanMessage(content=user_input),
        ]

    def _system_prompt(self) -> str:
        """构建循环的 system prompt。

        工具目录渲染为稳定的 JSON 块，让模型能被告知「通过产出
        ``{"action_type":"call_tool", "tool_name": "<name>", ...}``
        来决定调用哪个工具」而无需 schema 感知推理。原 tool-binding
        provider 忽略该目录（它们从绑定的工具中读取），但把它放进
        system prompt 在模型需要在 tool_call 与自由 JSON 之间二选一
        时有帮助。
        """

        catalog = json.dumps(
            [
                {"name": d.name, "description": d.description}
                for d in self._descriptors
            ],
            ensure_ascii=False,
        )
        return (
            "你是 Writer Agent 的工具循环(ReAct-style)。\n"
            "你的任务是:\n"
            "1. 阅读用户输入与对话历史(含历史 tool 结果)。\n"
            "2. 决定下一步:\n"
            "   - 调用工具 → 输出 {\"action_type\":\"call_tool\","
            " \"tool_name\": \"<name>\", \"arguments\": {...}}\n"
            "   - 给出最终回答 → 输出 {\"action_type\":\"answer_directly\","
            " \"answer\": \"<text>\"}\n"
            f"可用工具目录:\n{catalog}\n"
        )

    async def _invoke_model(self, messages: list[BaseMessage]) -> AIMessage:
        """用合适的 provider 路径调用模型。

        JSON-prompt 路径下也返回 :class:`AIMessage` —— 下游解析统一。
        """

        if self._use_json_prompt:
            assert self._llm is not None  # 通过 provider 装配收窄
            parsed = invoke_structured_json(self._llm, messages, AgentAction)
            return AIMessage(
                content=parsed.model_dump_json(),
                # 通过 ``additional_kwargs`` 携带解析后的 action，
                # 让 ``_parse_ai_message`` 能识别 JSON-prompt 路径
                # 而无需重跑 ``invoke_structured_json``。
                additional_kwargs={"_json_action": parsed},
            )
        assert self._bound_llm is not None
        ai_message = await self._bound_llm.ainvoke(messages)
        if not isinstance(ai_message, AIMessage):
            # 防御性：某些 LangChain adapter 返回 BaseMessage；
            # 强制转换让下游解析统一。
            ai_message = AIMessage(content=str(ai_message.content))
        return ai_message

    def _parse_ai_message(self, ai_message: AIMessage) -> AgentAction | None:
        """从 ``AIMessage`` 提取 :class:`AgentAction`。

        解析顺序：

        1. ``AIMessage.tool_calls`` —— 原生 binding 路径。
        2. ``AIMessage.additional_kwargs["_json_action"]`` —— JSON-prompt
           路径；预先校验的 action 由 ``_invoke_model`` 附加。
        3. ``AIMessage.content`` 解析为 JSON —— 当模型在自由文本中
           而非结构化契约中产出 action 时的 JSON-prompt 回退。
        4. 无 tool_calls 的纯文本内容 —— 模型用散文回答；视为
           ``answer_directly``，让循环终止。

        仅当模型*毫无*可执行内容时（空 content + 无 tool_calls）才
        返回 ``None`` —— 该情形在调用处变为软失败。
        """

        tool_calls = getattr(ai_message, "tool_calls", None) or []
        if tool_calls:
            first = tool_calls[0]
            tool_name = str(first.get("name", "") or "")
            raw_args = first.get("args", {}) or {}
            arguments = dict(raw_args) if isinstance(raw_args, dict) else {}
            if tool_name:
                return AgentAction(
                    action_type="call_tool",
                    tool_name=tool_name,
                    arguments=arguments,
                )

        json_action = ai_message.additional_kwargs.get("_json_action")
        if isinstance(json_action, AgentAction):
            return json_action

        content = ai_message.content
        text_content = ""
        if isinstance(content, str):
            text_content = content
        elif isinstance(content, list):
            # 多段内容（新版 provider 的 LC 标准）：只取文本段，让
            # ``json.loads`` 不会在 list 中非 JSON dict 上崩溃。
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            text_content = "\n".join(parts)

        stripped = text_content.strip()
        if stripped:
            # 先尝试 JSON 解析（结构化响应）。
            try:
                payload = json.loads(stripped)
                if isinstance(payload, dict) and "action_type" in payload:
                    return AgentAction.model_validate(payload)
            except json.JSONDecodeError:
                pass
            # 不是 JSON：模型产出纯文本回答。视为 ``answer_directly``，
            # 让「不再需要工具，直接回答」的 ReAct 循环干净终止。
            return AgentAction(
                action_type="answer_directly",
                answer=text_content,
            )
        return None

    def _build_tool_message(
        self,
        ai_message: AIMessage,
        tool_name: str,
        output: str,
    ) -> ToolMessage:
        """把工具结果包装为 :class:`ToolMessage` 给模型。

        原生 provider 要求 ``tool_call_id``；JSON-prompt provider 忽略
        它但接受该字段。我们从对应的 ``AIMessage.tool_calls`` 条目
        中抽取 id（可用时），否则用从工具名派生的合成 id，让
        JSON-prompt 路径无需额外记账。
        """

        tool_call_id = ""
        tool_calls = getattr(ai_message, "tool_calls", None) or []
        for entry in tool_calls:
            if str(entry.get("name", "") or "") == tool_name:
                tool_call_id = str(entry.get("id", "") or "")
                break
        if not tool_call_id:
            tool_call_id = f"{tool_name}-{len(self._descriptors)}"
        return ToolMessage(content=output, tool_call_id=tool_call_id)

    def _budget_fallback(self, state: ToolLoopState) -> str:
        """构建预算耗尽时的兜底块。

        让用户知情：打印跑了几步并展示最后一次工具输出的尾部，让
        他们无需再次提问就能手动接着往下走。
        """

        head = (
            f"工具调用已达上限 ({state.tool_calls_made}/{MAX_LOOP_STEPS});"
            " 请基于以下最近结果继续追问或缩小范围："
        )
        last = state.last_tool_result.output if state.last_tool_result else "(无)"
        # 限制尾部大小，避免把巨型 payload 推回给用户。
        tail = last if len(last) <= 200 else last[:200] + "..."
        return f"{head}\n{tail}"


__all__ = ["LLMToolLoop", "MAX_LOOP_STEPS", "ToolLoopState"]
