"""LLM-driven multi-step tool loop (ReAct-style).

``LlmIntentRouter`` is a one-shot translator: the LLM sees the user input,
emits a single ``AgentAction``, and exits. That is fine for routing, but
it means the model never sees the result of the tool it just called, so a
multi-hop query like *"搜一下玉佩，再告诉我它在第几章"* has to be split
across two REPL turns.

:mod:`writer.llm.agent` lifts the engine's tool invocation out of the
outer state machine and into a ReAct-style loop:

* Each step the LLM is invoked with the full conversation (system
  prompt + tool catalog + prior tool results).
* The model either emits an ``AgentAction`` of type ``answer_directly``
  (loop ends) or a ``call_tool`` (loop invokes the tool via the
  :class:`writer.tools.ToolRegistry`, appends a ``ToolMessage`` to the
  history, and re-asks the model).
* A hard ``MAX_LOOP_STEPS`` budget caps the number of tool calls so a
  pathological model cannot loop forever. When the budget is exhausted,
  the loop yields a fallback ``TextChunk`` summarising the last tool
  output and terminates with a ``Done(tool_loop_completed)``.

The loop is a separate concern from the engine state machine — the
engine still owns per-turn context, REPL routing, and the outer
``Done`` event. The loop is **delegated to** from ``engine.loop`` only
when the router's first action is ``call_tool`` and a ``tool_loop`` is
configured on the engine deps; rule-first dispatch and the non-LLM
``_run_tool`` path remain untouched.

Layering: this module lives under ``writer.llm`` (not ``writer.engine``)
so the engine package never imports LLM types directly. ``EngineDeps``
holds an ``Optional[LLMToolLoop]`` reference; when the engine wants the
loop it ``await deps.tool_loop.run(...)`` and forwards the yielded
events unchanged.
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

# Hard upper bound on tool calls per turn. A real ReAct agent can
# accumulate useful context quickly; a runaway model that keeps calling
# the same tool is almost always broken or hallucinating. 5 is generous
# enough for "search → locate" chains while keeping the worst-case token
# spend predictable.
MAX_LOOP_STEPS = 5


@dataclass
class ToolLoopState:
    """Per-turn state for the LLM tool loop.

    Lifecycle is single-turn: the engine constructs a fresh state every
    time it delegates to ``LLMToolLoop.run``. Cross-turn memory would
    belong to ``EngineSession`` (intentionally out of scope per the plan).

    Attributes:
        messages: LangChain message history. Starts with the loop's
            system prompt + a human turn for the user's input, and
            accumulates ``AIMessage`` / ``ToolMessage`` pairs as the loop
            iterates.
        tool_calls_made: Counter incremented after each successful tool
            invocation. Drives the budget check.
        last_tool_result: Most recent :class:`writer.tools.ToolResult`
            produced by the loop. Used for the fallback ``TextChunk``
            when the budget is exhausted and for the ``Done`` payload.
    """

    messages: list[BaseMessage] = field(default_factory=list)
    tool_calls_made: int = 0
    last_tool_result: ProtocolToolResult | None = None


class LLMToolLoop:
    """Drive an LLM through multiple tool calls until it answers.

    Two provider paths are supported, mirroring
    :class:`writer.routing.LlmIntentRouter`:

    * **Native structured output** — ``llm.bind_tools(...)`` is used for
      OpenAI-compatible providers that honor the ``tools`` field on the
      request. The model emits ``AIMessage`` objects whose
      ``tool_calls`` attribute carries the structured invocation.
    * **JSON-prompt structured output** — providers like DeepSeek reject
      the native tool-binding payload, so the tool catalog is serialised
      into the system prompt and the model emits a JSON ``AgentAction``.
      :func:`writer.llm.structured.invoke_structured_json` validates the
      payload against the same Pydantic schema used by the router.

    Construction:

    * ``LLMToolLoop(settings, registry, runtime)`` — production wiring
      via :func:`writer.llm.provider.get_llm`.
    * ``LLMToolLoop(..., llm=fake_chat_model)`` — test injection; bypasses
      :func:`get_llm`.
    * ``LLMToolLoop(..., langchain_tools=[...])`` — test injection;
      bypasses ``to_langchain_tools`` (which builds the closure over
      ``runtime``). Useful when the test wants to observe how the loop
      handles tool messages without needing a real registry wiring.
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
        # Native tool binding: build once so every step reuses the same
        # tool list. JSON-prompt providers also get the list built (for
        # future use) but the loop path uses the descriptors directly.
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
        deps: EngineDeps,  # noqa: ARG002 — kept for symmetry with engine helpers
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
        """Drive the ReAct loop until ``answer_directly`` or budget exhaustion.

        ``action`` is the router's first ``call_tool`` decision for this
        turn. We use it to seed the conversation history (so the model
        knows what the user asked, even if its first action was a tool
        call rather than a text answer). ``ctx`` carries the original
        user input via ``EngineContext.user_input``.

        Exceptions from tool invocations propagate upward — the engine's
        outer ``except ToolError`` boundary is the single funnel for
        surfacing tool failures; we do not swallow them here so the
        same ``ErrorEvent + Done(aborted)`` UX applies.
        """

        del deps  # currently unused; kept in the signature for future hooks
        del cfg  # currently unused; reserved for future per-loop config

        state = ToolLoopState(
            messages=self._initial_messages(action, ctx.user_input),
        )

        while state.tool_calls_made < MAX_LOOP_STEPS:
            ai_message = await self._invoke_model(state.messages)
            state.messages.append(ai_message)

            parsed = self._parse_ai_message(ai_message)
            if parsed is None:
                # The model emitted nothing actionable (no tool_calls,
                # no parseable JSON). Treat as a soft failure: yield a
                # fallback answer and stop the loop.
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

            # ToolError intentionally re-raised so the engine's outer
            # ``except ToolError`` boundary produces ErrorEvent +
            # Done(aborted) with the same UX as the rule-first path.
            result = self._registry.invoke(
                tool_name, self._runtime, **arguments
            )
            state.last_tool_result = result
            state.messages.append(
                self._build_tool_message(ai_message, tool_name, result.output)
            )
            yield ToolResult(name=tool_name, output=result.output)
            state.tool_calls_made += 1

        # Budget exhausted. Yield a fallback chunk that surfaces what
        # the last tool returned so the user has something actionable,
        # then terminate with a non-error Done reason — the budget
        # being reached is a *graceful* state, not a failure.
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
        self, action: AgentAction, user_input: str
    ) -> list[BaseMessage]:
        """Seed the conversation with system prompt + user turn.

        The system prompt embeds the tool catalog (name + description)
        for JSON-prompt providers and the model name/version banner for
        all providers so the log history is self-describing.
        """

        system = self._system_prompt()
        return [SystemMessage(content=system), HumanMessage(content=user_input)]

    def _system_prompt(self) -> str:
        """Build the loop's system prompt.

        Tool catalog is rendered as a stable JSON block so the model
        can be told "decide which tool to call by emitting
        ``{"action_type":"call_tool", "tool_name": "<name>", ...}``"
        without needing schema-aware reasoning. Native tool-binding
        providers ignore the catalog (they read it from the bound tools)
        but having it in the system prompt helps when the model is
        asked to choose between tool_call and free-form JSON.
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
        """Call the model with the right provider path.

        Returns an :class:`AIMessage` even on the JSON-prompt path —
        downstream parsing is uniform.
        """

        if self._use_json_prompt:
            assert self._llm is not None  # narrowed by provider wiring
            parsed = invoke_structured_json(self._llm, messages, AgentAction)
            return AIMessage(
                content=parsed.model_dump_json(),
                # Carry the parsed action through ``additional_kwargs``
                # so ``_parse_ai_message`` can detect the JSON-prompt
                # path without re-running ``invoke_structured_json``.
                additional_kwargs={"_json_action": parsed},
            )
        assert self._bound_llm is not None
        ai_message = await self._bound_llm.ainvoke(messages)
        if not isinstance(ai_message, AIMessage):
            # Defensive: some LangChain adapters return BaseMessage;
            # coerce so downstream parsing is uniform.
            ai_message = AIMessage(content=str(ai_message.content))
        return ai_message

    def _parse_ai_message(self, ai_message: AIMessage) -> AgentAction | None:
        """Extract an :class:`AgentAction` from an ``AIMessage``.

        Resolution order:

        1. ``AIMessage.tool_calls`` — native binding path.
        2. ``AIMessage.additional_kwargs["_json_action"]`` — JSON-prompt
           path; the pre-validated action is attached by ``_invoke_model``.
        3. ``AIMessage.content`` parsed as JSON — JSON-prompt fallback when
           the model emits the action in its free-form text rather than
           via the structured contract.
        4. Plain text content with no tool calls — model is answering in
           prose; treat as ``answer_directly`` so the loop terminates.

        Returns ``None`` only when the model emits *nothing* actionable
        (empty content + no tool_calls) — that case becomes a soft
        failure at the call site.
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
            # Multi-part content (LC standard for newer providers): take
            # only the text parts so ``json.loads`` doesn't choke on
            # non-JSON dicts in the list.
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
            # Try JSON parse first (structured response).
            try:
                payload = json.loads(stripped)
                if isinstance(payload, dict) and "action_type" in payload:
                    return AgentAction.model_validate(payload)
            except json.JSONDecodeError:
                pass
            # Not JSON: model emitted a plain-text answer. Treat as
            # ``answer_directly`` so a ReAct loop that decides "no
            # more tools needed, just answer" terminates cleanly.
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
        """Wrap a tool result as a :class:`ToolMessage` for the model.

        Native providers require ``tool_call_id``; JSON-prompt providers
        ignore it but accept the field. We pull the id from the
        corresponding ``AIMessage.tool_calls`` entry when available,
        falling back to a synthetic id derived from the tool name so the
        JSON-prompt path doesn't need extra bookkeeping.
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
        """Build the budget-exhausted fallback chunk.

        Keeps the user informed: prints how many steps ran and surfaces
        the tail of the last tool output so they can pick up manually
        without re-asking.
        """

        head = (
            f"工具调用已达上限 ({state.tool_calls_made}/{MAX_LOOP_STEPS});"
            " 请基于以下最近结果继续追问或缩小范围："
        )
        last = state.last_tool_result.output if state.last_tool_result else "(无)"
        # Cap the tail to avoid pushing a giant payload back to the user.
        tail = last if len(last) <= 200 else last[:200] + "..."
        return f"{head}\n{tail}"


__all__ = ["LLMToolLoop", "MAX_LOOP_STEPS", "ToolLoopState"]
