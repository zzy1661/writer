"""Unit tests for the LLM-driven tool loop (``LLMToolLoop``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from writer.config import Settings
from writer.engine import (
    Done,
    EngineContext,
    ErrorEvent,
    TextChunk,
    ToolCall,
    ToolResult,
    run_engine,
)
from writer.engine.config import build_engine_config
from writer.engine.deps import _DefaultEngineDeps
from writer.llm.agent import MAX_LOOP_STEPS, LLMToolLoop
from writer.roles import StoryConsultant
from writer.routing import AgentAction, IntentRouter
from writer.skills import built_skill_registry
from writer.tools import ToolRuntime, built_tool_registry
from writer.tools.errors import ToolError, ToolNotFoundError

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _ScriptedChat(BaseChatModel):
    """Minimal scripted chat model that returns AIMessages in sequence.

    Each ``ainvoke`` pops the next ``tool_calls`` / content payload from
    ``self._script``. The model advertises no real ``bind_tools``
    support, but ``LLMToolLoop`` is happy because it just calls
    ``ainvoke`` on whatever the bound LLM returns.

    Each script entry is a dict:

    * ``{"tool_calls": [{"name", "args", "id"}]}`` — emit a tool call.
    * ``{"content": "..."}`` — emit a final text answer (no tool calls).

    The script is consumed in order; if the loop runs longer than the
    script the model raises ``RuntimeError`` so the test fails loudly
    instead of silently repeating the last answer.
    """

    _script: list[dict[str, Any]] = PrivateAttr()
    _calls: int = PrivateAttr(default=0)

    def __init__(self, script: list[dict[str, Any]]) -> None:
        super().__init__()
        self._script = list(script)
        self._calls = 0

    @property
    def call_count(self) -> int:
        return self._calls

    @property
    def _llm_type(self) -> str:
        # ``BaseChatModel`` requires this; the loop doesn't read it but
        # instantiation fails without it.
        return "scripted-fake"

    async def _agenerate(self, messages: Any, **kwargs: Any) -> ChatResult:
        if not self._script:
            msg = f"scripted chat ran out of responses after {self._calls} calls"
            raise RuntimeError(msg)
        self._calls += 1
        return ChatResult(generations=[ChatGeneration(message=_scripted_to_ai(self._script.pop(0)))])

    def _generate(self, messages: Any, **kwargs: Any) -> ChatResult:
        # Sync fallback that mirrors ``_agenerate``. Keeps the contract
        # honest for any code path that inadvertently calls sync.
        if not self._script:
            msg = f"scripted chat ran out of responses after {self._calls} calls"
            raise RuntimeError(msg)
        self._calls += 1
        return ChatResult(generations=[ChatGeneration(message=_scripted_to_ai(self._script.pop(0)))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> _ScriptedChat:
        # ``LLMToolLoop`` calls ``bind_tools`` at construction time on the
        # native (OpenAI-compatible) path. The fake doesn't read the tool
        # list — the test script decides which tool_calls to emit — so
        # we just return ``self`` and let ``ainvoke`` dispatch.
        del tools, kwargs
        return self


def _scripted_to_ai(entry: dict[str, Any]) -> AIMessage:
    """Convert a script entry to an AIMessage.

    Tool-call entries become ``AIMessage.tool_calls``; content entries
    become ``AIMessage.content``. Both go through the same fields
    ``_parse_ai_message`` reads, so the test exercises the production
    parser rather than a parallel one.
    """

    if "tool_calls" in entry:
        return AIMessage(content="", tool_calls=entry["tool_calls"])
    if "content" in entry:
        return AIMessage(content=entry["content"])
    msg = f"script entry must have 'tool_calls' or 'content': {entry!r}"
    raise ValueError(msg)


def _settings() -> Settings:
    """Plain settings instance — LLMToolLoop does not need a real key."""

    return Settings(
        model="gpt-4o-mini",
        api_key=None,
        base_url="https://api.openai.com/v1",
        temperature=0.0,
    )


def _ctx(user_input: str = "玉佩出现在哪里") -> EngineContext:
    return EngineContext(
        user_input=user_input,
        project_root=Path("/__no_project__"),
        project_state="S2",
        session_id="test-session",
    )


async def _consume(
    iterator: AsyncIterator[Any],
) -> list[Any]:
    """Drain an async iterator into a list for assertion."""

    out: list[Any] = []
    async for event in iterator:
        out.append(event)
    return out


# ---------------------------------------------------------------------------
# Test 2 — two-step loop: tool_call, then answer
# ---------------------------------------------------------------------------


async def test_llm_tool_loop_two_steps() -> None:
    """A two-step loop yields 1 ToolCall+ToolResult pair, then Done(answered)."""

    script = [
        {
            "tool_calls": [
                {
                    "name": "project_search",
                    "args": {"query": "玉佩", "path": "."},
                    "id": "tc1",
                }
            ]
        },
        {"content": "玉佩出现在第3章"},
    ]
    chat = _ScriptedChat(script)
    registry = built_tool_registry()
    runtime = ToolRuntime(project_root=Path("/__no_project__"))
    loop = LLMToolLoop(
        _settings(),
        registry=registry,
        runtime=runtime,
        llm=chat,
    )

    action = AgentAction(
        action_type="call_tool",
        tool_name="project_search",
        arguments={"query": "玉佩", "path": "."},
    )
    cfg = build_engine_config(_ctx())
    events = await _consume(loop.run(action, _ctx(), _noop_deps(), cfg))

    # One ToolCall + one ToolResult for the single tool invocation.
    tool_calls = [e for e in events if isinstance(e, ToolCall)]
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert len(tool_calls) == 1
    assert len(tool_results) == 1
    assert tool_calls[0].name == "project_search"
    assert tool_results[0].name == "project_search"

    # Final answer chunk + Done(answered) with the budget consumed.
    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected a terminal Done event"
    assert done_events[-1].reason == "answered"
    assert done_events[-1].payload is not None
    assert done_events[-1].payload["tool_calls_made"] == 1

    # The answer chunk must carry the model's final text.
    answer_chunks = [
        e for e in events if isinstance(e, TextChunk) and "玉佩出现在第3章" in e.text
    ]
    assert answer_chunks, "expected an answer chunk containing the model's text"
    # The scripted chat should have been called twice (1 tool + 1 answer).
    assert chat.call_count == 2


# ---------------------------------------------------------------------------
# Test 3 — budget exhaustion: model always emits tool_call
# ---------------------------------------------------------------------------


async def test_llm_tool_loop_budget_exhausted() -> None:
    """When the model never answers, the loop terminates after MAX_LOOP_STEPS."""

    registry = built_tool_registry()
    runtime = ToolRuntime(project_root=Path("/__no_project__"))
    # Tool that always succeeds so the loop isn't short-circuited by errors.
    script = [
        {
            "tool_calls": [
                {
                    "name": "project_search",
                    "args": {"query": "玉佩", "path": "."},
                    "id": f"tc{i}",
                }
            ]
        }
        for i in range(MAX_LOOP_STEPS)
    ]
    chat = _ScriptedChat(script)
    loop = LLMToolLoop(_settings(), registry=registry, runtime=runtime, llm=chat)

    action = AgentAction(
        action_type="call_tool",
        tool_name="project_search",
        arguments={"query": "玉佩", "path": "."},
    )
    cfg = build_engine_config(_ctx())
    events = await _consume(loop.run(action, _ctx(), _noop_deps(), cfg))

    tool_calls = [e for e in events if isinstance(e, ToolCall)]
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert len(tool_calls) == MAX_LOOP_STEPS
    assert len(tool_results) == MAX_LOOP_STEPS

    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected a terminal Done event"
    last = done_events[-1]
    assert last.reason == "tool_loop_completed"
    assert last.payload is not None
    assert last.payload["tool_calls_made"] == MAX_LOOP_STEPS

    # The fallback TextChunk must mention the budget exhaustion.
    fallback_chunks = [
        e
        for e in events
        if isinstance(e, TextChunk)
        and "上限" in e.text
        and f"{MAX_LOOP_STEPS}/{MAX_LOOP_STEPS}" in e.text
    ]
    assert fallback_chunks, "expected a fallback TextChunk mentioning the budget"
    assert chat.call_count == MAX_LOOP_STEPS


# ---------------------------------------------------------------------------
# Test 4 — unknown tool name: ToolError propagates through the loop
# ---------------------------------------------------------------------------


class _UnknownToolRouter(IntentRouter):
    """Routes the first turn into a ``call_tool`` with an unknown name."""

    def route(self, user_input: str, project_state: str) -> AgentAction:
        return AgentAction(
            action_type="call_tool",
            tool_name="not_a_tool",
            arguments={},
        )


def _noop_deps() -> _DefaultEngineDeps:
    """Construct a deps instance with ``tool_loop=None``.

    Used by the loop's direct tests — they don't need a real deps, the
    loop ignores ``deps`` after the initial signature plumb.
    """

    return _DefaultEngineDeps(
        router=_UnknownToolRouter(),
        story_consultant=StoryConsultant(_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        skill_registry=built_skill_registry(),
        tool_loop=None,
    )


async def test_llm_tool_loop_unknown_tool_name_propagates_tool_error() -> None:
    """``ToolNotFoundError`` raised by the registry propagates as ``ToolError``."""

    chat = _ScriptedChat(
        [
            {
                "tool_calls": [
                    {
                        "name": "not_a_tool",
                        "args": {},
                        "id": "tc-bad",
                    }
                ]
            },
        ]
    )
    registry = built_tool_registry()
    runtime = ToolRuntime(project_root=Path("/__no_project__"))
    loop = LLMToolLoop(_settings(), registry=registry, runtime=runtime, llm=chat)

    action = AgentAction(
        action_type="call_tool",
        tool_name="not_a_tool",
        arguments={},
    )
    cfg = build_engine_config(_ctx())
    events_gen = loop.run(action, _ctx(), _noop_deps(), cfg)

    raised: ToolError | None = None
    try:
        async for _event in events_gen:
            pass
    except ToolError as exc:
        raised = exc

    assert raised is not None, "expected ToolError to propagate"
    assert isinstance(raised, ToolNotFoundError)
    assert "not_a_tool" in str(raised)


async def test_engine_loop_emits_error_event_for_unknown_tool_via_tool_loop() -> None:
    """End-to-end: engine sees ``ToolNotFoundError`` and yields ErrorEvent + Done(aborted).

    This test stands up a minimal ``_DefaultEngineDeps`` whose
    ``tool_loop`` is wired to a fake LLM that emits an unknown tool
    name. The engine's outer ``except ToolError`` boundary must turn
    the propagation into the same ``ErrorEvent + Done(aborted)`` UX
    the synchronous ``_run_tool`` path uses.
    """

    from pydantic import SecretStr

    settings = Settings(
        model="gpt-4o-mini",
        api_key=SecretStr("sk-test"),
        base_url="https://api.openai.com/v1",
        temperature=0.0,
    )
    chat = _ScriptedChat(
        [
            {
                "tool_calls": [
                    {
                        "name": "not_a_tool",
                        "args": {},
                        "id": "tc-bad",
                    }
                ]
            },
        ]
    )
    registry = built_tool_registry()
    runtime = ToolRuntime(project_root=Path("/__no_project__"))
    tool_loop = LLMToolLoop(settings, registry=registry, runtime=runtime, llm=chat)

    deps = _DefaultEngineDeps(
        router=_UnknownToolRouter(),
        story_consultant=StoryConsultant(settings),
        tool_registry=registry,
        tool_runtime=runtime,
        skill_registry=built_skill_registry(),
        tool_loop=tool_loop,
    )
    ctx = _ctx()
    events = await _consume(run_engine(ctx, deps))

    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    aborted = [e for e in events if isinstance(e, Done) and e.reason == "aborted"]
    assert error_events, "expected an ErrorEvent for the unknown tool"
    assert "not_a_tool" in error_events[0].message
    assert aborted, "expected a Done(aborted) event"
    assert aborted[-1].payload is not None
    assert "not_a_tool" in str(aborted[-1].payload["error"])
