"""Unit tests for the agent engine MVP."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from writer.engine import (
    ActionEvent,
    Done,
    EngineContext,
    TextChunk,
    production_deps,
    run_engine,
)
from writer.engine.deps import EngineDeps
from writer.project import create_workspace, detect_state
from writer.routing import (
    AgentAction,
    IntentRouter,
    RuleBasedIntentRouter,
)

# ---------------------------------------------------------------------------
# Router classification
# ---------------------------------------------------------------------------


def test_router_classifies_write_command() -> None:
    action = RuleBasedIntentRouter().route("/写 1.3", "S0")

    assert action.action_type == "start_workflow"
    assert action.workflow == "write_chapter"
    assert action.role == "story_consultant"
    assert action.command == "/写"


def test_router_classifies_review_command() -> None:
    action = RuleBasedIntentRouter().route("/审核 第3章", "S2")

    assert action.action_type == "start_workflow"
    assert action.workflow == "review_chapter"
    assert action.role == "reviewer"
    assert action.command == "/审核"


def test_router_classifies_tool_query() -> None:
    action = RuleBasedIntentRouter().route("查一下 F003 伏笔出现位置", "S2")

    assert action.action_type == "call_tool"
    assert action.tool_name == "foreshadow_query"
    assert action.role == "story_consultant"
    assert action.arguments == {"query": "查一下 F003 伏笔出现位置"}


def test_router_classifies_read_file_command() -> None:
    action = RuleBasedIntentRouter().route("/查看 outline/大纲.md", "S2")

    assert action.action_type == "call_tool"
    assert action.command == "/查看"
    assert action.tool_name == "safe_read_file"
    assert action.arguments == {"path": "outline/大纲.md"}


def test_router_classifies_search_command() -> None:
    action = RuleBasedIntentRouter().route("/搜索 玉簪", "S2")

    assert action.action_type == "call_tool"
    assert action.command == "/搜索"
    assert action.tool_name == "project_search"
    assert action.arguments == {"query": "玉簪", "path": "."}


def test_router_classifies_wordcount_command() -> None:
    action = RuleBasedIntentRouter().route("/字数统计 manuscript", "S2")

    assert action.action_type == "call_tool"
    assert action.command == "/字数统计"
    assert action.tool_name == "wordcount"
    assert action.arguments == {"path": "manuscript"}


def test_router_classifies_init_command() -> None:
    action = RuleBasedIntentRouter().route("/init", "S0")

    assert action.action_type == "run_command"
    assert action.command == "/init"


def test_router_falls_back_to_answer() -> None:
    action = RuleBasedIntentRouter().route("帮我润色下这段", "S2")

    assert action.action_type == "answer_directly"
    assert action.answer is not None
    assert "帮我润色下这段" in action.answer


def test_rule_based_router_satisfies_protocol() -> None:
    """Concrete implementation must satisfy :class:`IntentRouter` (runtime-checkable)."""

    router: IntentRouter = RuleBasedIntentRouter()
    assert isinstance(router, IntentRouter)


# ---------------------------------------------------------------------------
# Engine loop terminal events
# ---------------------------------------------------------------------------


def _consume(events: AsyncIterator[object]) -> list[object]:
    """Drain an async generator synchronously for tests."""

    import asyncio

    async def drain() -> list[object]:
        return [event async for event in events]

    return asyncio.run(drain())


def _ctx(
    text: str,
    *,
    project_root: Path | None = None,
    project_state: str = "S0",
) -> EngineContext:
    return EngineContext(
        user_input=text,
        project_root=project_root,
        project_state=project_state,
        session_id="test-session",
    )


def _workspace_ctx(text: str, root: Path) -> EngineContext:
    return _ctx(
        text,
        project_root=root,
        project_state=detect_state(root).value,
    )


def test_engine_yields_done_for_answer() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("帮我润色下这段"), deps))

    assert any(isinstance(e, TextChunk) and "[engine] 分析输入" in e.text for e in events)
    assert any(isinstance(e, ActionEvent) and e.action.action_type == "answer_directly" for e in events)
    assert any(isinstance(e, Done) and e.reason == "answered" for e in events)


def test_engine_yields_done_for_workflow(tmp_path: Path) -> None:
    deps = production_deps()
    workspace = create_workspace("workflow-test", tmp_path)
    (workspace.root / "outline" / "toc.md").write_text("第一章", encoding="utf-8")

    events = _consume(run_engine(_workspace_ctx("/写 1.3", workspace.root), deps))

    assert any(isinstance(e, ActionEvent) and e.action.workflow == "write_chapter" for e in events)
    assert any(isinstance(e, Done) and e.reason == "workflow_pending" for e in events)


def test_engine_yields_done_for_tool() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("查一下 F003"), deps))

    from writer.engine import ToolCall, ToolResult

    assert any(isinstance(e, ActionEvent) and e.action.tool_name == "foreshadow_query" for e in events)
    assert any(isinstance(e, ToolCall) and e.name == "foreshadow_query" for e in events)
    assert any(isinstance(e, ToolResult) and e.name == "foreshadow_query" for e in events)
    assert any(isinstance(e, Done) and e.reason == "tool_completed" for e in events)


def test_engine_yields_done_for_command() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("/未知命令"), deps))

    assert any(isinstance(e, ActionEvent) and e.action.command == "/未知命令" for e in events)
    assert any(isinstance(e, Done) and e.reason == "command_pending" for e in events)


def test_production_deps_has_router() -> None:
    deps = production_deps()

    assert isinstance(deps, EngineDeps)
    # When the local .env has no API key, router is the bare rule router.
    # When it does (e.g. the user's .env in this repo), router is wrapped
    # in a CompositeRouter. Both satisfy IntentRouter.
    from writer.routing import IntentRouter

    assert isinstance(deps.router, IntentRouter)
    from writer.roles import StoryConsultant

    assert isinstance(deps.story_consultant, StoryConsultant)

    action: AgentAction = deps.route("/init", "S0")
    assert action.action_type == "run_command"


# ---------------------------------------------------------------------------
# Wiring integration (Phase 2)
# ---------------------------------------------------------------------------


def test_engine_runs_outline_via_story_consultant(tmp_path: Path) -> None:
    """``/大纲 <创意>`` must stream the outline from StoryConsultant and yield ``answered``."""
    deps = production_deps()
    workspace = create_workspace("outline-test", tmp_path)

    events = _consume(
        run_engine(_workspace_ctx("/大纲 双主角女将军从冷宫到朝堂", workspace.root), deps)
    )

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    action_events = [e for e in events if isinstance(e, ActionEvent)]
    done_events = [e for e in events if isinstance(e, Done)]

    assert any(isinstance(e, ActionEvent) and e.action.action_type == "run_command" for e in action_events)
    assert any(isinstance(e, ActionEvent) and e.action.command == "/大纲" for e in action_events)
    assert "StoryConsultant" in text_blob
    assert "双主角女将军从冷宫到朝堂" in text_blob
    assert "第一幕" in text_blob
    assert "第四幕" in text_blob
    assert (workspace.root / "outline" / "大纲.md").is_file()

    answered = [e for e in done_events if e.reason == "answered"]
    assert answered, "expected at least one Done(reason='answered')"
    assert answered[0].payload is not None
    assert answered[0].payload.get("outline") is True
    assert answered[0].payload.get("chapter_count") == 4
    assert answered[0].payload.get("project_state") == "S2"


def test_engine_streams_workflow_stub_chunks(tmp_path: Path) -> None:
    """``start_workflow`` must dispatch to the registered LangGraph workflow."""
    deps = production_deps()
    workspace = create_workspace("workflow-test", tmp_path)
    (workspace.root / "outline" / "toc.md").write_text("第一章", encoding="utf-8")

    events = _consume(run_engine(_workspace_ctx("/写 1.3", workspace.root), deps))

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))

    assert "[workflow] LangGraph write_chapter 图完成" in text_blob
    assert "prep_context" in text_blob
    assert "review_gate" in text_blob
    assert any(isinstance(e, Done) and e.reason == "workflow_pending" for e in events)


def test_engine_blocks_write_before_toc() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("/写 1.3"), deps))

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "/写 当前不可用" in text_blob
    assert any(isinstance(e, Done) and e.reason == "aborted" for e in events)


def test_engine_workflow_unknown_name_raises_domain_error() -> None:
    """Unknown workflow names should raise WorkflowNotFoundError, not return a placeholder chunk.

    Per arch-optimizer m18 (2026-07-05): the previous behavior of
    returning a ``[workflow] 未知工作流 ...`` chunk looked like a
    legitimate workflow response to the user. Now the engine surfaces
    it as a ``ToolError`` via the existing ``except ToolError`` branch
    in ``_engine_loop`` -> ``ErrorEvent`` + ``Done(aborted)``.
    """
    from pathlib import Path

    import pytest

    from writer.config import get_settings
    from writer.engine.deps import _DefaultEngineDeps
    from writer.roles import StoryConsultant
    from writer.routing import RuleBasedIntentRouter
    from writer.tools import ToolRuntime, built_tool_registry
    from writer.tools.errors import WorkflowNotFoundError

    deps = _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        story_consultant=StoryConsultant(get_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        _workflows={},
    )

    with pytest.raises(WorkflowNotFoundError) as exc_info:
        deps.run_workflow("not_a_real_workflow", _ctx("ignored"))

    assert "not_a_real_workflow" in str(exc_info.value)


def test_production_deps_includes_all_registered_workflows() -> None:
    """production_deps() must register every workflow in writer.workflows.WORKFLOWS."""
    from writer.workflows import WORKFLOWS

    deps = production_deps()

    for name in WORKFLOWS:
        chunks = list(deps.run_workflow(name, _ctx("ignored")))
        assert chunks, f"workflow {name!r} produced no chunks"


# ---------------------------------------------------------------------------
# Phase 3: Engine Loop branch wiring (add-llm-and-complete-engine-loop)
# ---------------------------------------------------------------------------


class _FailingRouter:
    """Stand-in router that raises on every call."""

    def route(self, user_input: str, project_state: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("router kaboom")


class _AskUserRouter:
    """Stand-in router that always returns an ask_user action."""

    def __init__(self, prompt: str = "你想修改哪一段？") -> None:
        self._prompt = prompt

    def route(self, user_input: str, project_state: str) -> AgentAction:
        return AgentAction(action_type="ask_user", user_prompt=self._prompt)


def test_engine_emits_error_event_on_router_failure() -> None:
    from writer.config import get_settings
    from writer.engine import ErrorEvent
    from writer.engine.deps import _DefaultEngineDeps
    from writer.roles import StoryConsultant
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=_FailingRouter(),  # type: ignore[arg-type]
        story_consultant=StoryConsultant(get_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
    )

    events = _consume(run_engine(_ctx("anything"), deps))

    assert any(isinstance(e, ErrorEvent) and "kaboom" in e.message for e in events)
    assert any(isinstance(e, Done) and e.reason == "aborted" for e in events)


def test_engine_emits_interrupt_for_ask_user_action() -> None:
    from writer.config import get_settings
    from writer.engine import Interrupt
    from writer.engine.deps import _DefaultEngineDeps
    from writer.roles import StoryConsultant
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=_AskUserRouter("你想修改哪一段？"),  # type: ignore[arg-type]
        story_consultant=StoryConsultant(get_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
    )

    events = _consume(run_engine(_ctx("模糊输入"), deps))

    interrupts = [e for e in events if isinstance(e, Interrupt)]
    assert interrupts, "expected an Interrupt event"
    assert interrupts[0].type == "text"
    assert "哪一段" in interrupts[0].prompt
    assert any(isinstance(e, Done) and e.reason == "ask_user" for e in events)


def test_engine_fast_mode_suppresses_engine_log_chunks() -> None:
    from writer.config import get_settings
    from writer.engine import TextChunk
    from writer.engine.config import EngineConfig
    from writer.engine.deps import _DefaultEngineDeps
    from writer.roles import StoryConsultant
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        story_consultant=StoryConsultant(get_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
    )

    cfg = EngineConfig(session_id="x", fast_mode=True)
    events = _consume(run_engine(_ctx("帮我润色下这段"), deps, config=cfg))

    # No diagnostic TextChunks starting with [engine]
    engine_logs = [
        e
        for e in events
        if isinstance(e, TextChunk) and e.text.startswith("[engine]")
    ]
    assert engine_logs == []

    # Business events still present
    assert any(isinstance(e, ActionEvent) for e in events)
    assert any(isinstance(e, Done) and e.reason == "answered" for e in events)


def test_engine_calls_tool_registry_on_call_tool_action() -> None:
    """Real call_tool path: registry invoked, ToolCall + ToolResult + tool_completed emitted."""
    from writer.config import get_settings
    from writer.engine import ToolCall, ToolResult
    from writer.engine.deps import _DefaultEngineDeps
    from writer.roles import StoryConsultant
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        story_consultant=StoryConsultant(get_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
    )

    events = _consume(run_engine(_ctx("查一下 F003"), deps))

    assert any(isinstance(e, ToolCall) and e.name == "foreshadow_query" for e in events)
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert tool_results, "expected ToolResult event"
    assert tool_results[0].name == "foreshadow_query"
    assert tool_results[0].output  # non-empty result
    assert any(isinstance(e, Done) and e.reason == "tool_completed" for e in events)


def test_engine_handles_tool_not_found_error() -> None:
    """A tool name that the registry doesn't know must yield ErrorEvent + Done(aborted)."""
    from writer.config import get_settings
    from writer.engine import ErrorEvent
    from writer.engine.deps import _DefaultEngineDeps
    from writer.roles import StoryConsultant
    from writer.routing import AgentAction
    from writer.tools import ToolRuntime, built_tool_registry

    class _CallUnknownTool:
        def route(self, user_input: str, project_state: str) -> AgentAction:
            return AgentAction(
                action_type="call_tool",
                tool_name="definitely_not_a_tool",
            )

    deps = _DefaultEngineDeps(
        router=_CallUnknownTool(),  # type: ignore[arg-type]
        story_consultant=StoryConsultant(get_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
    )

    events = _consume(run_engine(_ctx("anything"), deps))

    assert any(isinstance(e, ErrorEvent) and "definitely_not_a_tool" in e.message for e in events)
    assert any(isinstance(e, Done) and e.reason == "aborted" for e in events)
