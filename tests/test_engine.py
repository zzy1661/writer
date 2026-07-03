"""Unit tests for the agent engine MVP."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from writer.engine import (
    ActionEvent,
    Done,
    EngineContext,
    TextChunk,
    production_deps,
    run_engine,
)
from writer.engine.deps import EngineDeps
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


def _ctx(text: str) -> EngineContext:
    return EngineContext(
        user_input=text,
        project_root=None,
        project_state="S0",
        session_id="test-session",
    )


def test_engine_yields_done_for_answer() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("帮我润色下这段"), deps))

    assert any(isinstance(e, TextChunk) and "[engine] 分析输入" in e.text for e in events)
    assert any(isinstance(e, ActionEvent) and e.action.action_type == "answer_directly" for e in events)
    assert any(isinstance(e, Done) and e.reason == "answered" for e in events)


def test_engine_yields_done_for_workflow() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("/写 1.3"), deps))

    assert any(isinstance(e, ActionEvent) and e.action.workflow == "write_chapter" for e in events)
    assert any(isinstance(e, Done) and e.reason == "workflow_pending" for e in events)


def test_engine_yields_done_for_tool() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("查一下 F003"), deps))

    assert any(isinstance(e, ActionEvent) and e.action.tool_name == "foreshadow_query" for e in events)
    assert any(isinstance(e, Done) and e.reason == "tool_pending" for e in events)


def test_engine_yields_done_for_command() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("/init"), deps))

    assert any(isinstance(e, ActionEvent) and e.action.command == "/init" for e in events)
    assert any(isinstance(e, Done) and e.reason == "command_pending" for e in events)


def test_production_deps_has_router() -> None:
    deps = production_deps()

    assert isinstance(deps, EngineDeps)
    assert isinstance(deps.router, RuleBasedIntentRouter)
    from writer.roles import StoryConsultant

    assert isinstance(deps.story_consultant, StoryConsultant)

    action: AgentAction = deps.route("/init", "S0")
    assert action.action_type == "run_command"


# ---------------------------------------------------------------------------
# Wiring integration (Phase 2)
# ---------------------------------------------------------------------------


def test_engine_runs_outline_via_story_consultant() -> None:
    """``/大纲 <创意>`` must stream the outline from StoryConsultant and yield ``answered``."""
    deps = production_deps()

    events = _consume(run_engine(_ctx("/大纲 双主角女将军从冷宫到朝堂"), deps))

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    action_events = [e for e in events if isinstance(e, ActionEvent)]
    done_events = [e for e in events if isinstance(e, Done)]

    assert any(isinstance(e, ActionEvent) and e.action.action_type == "run_command" for e in action_events)
    assert any(isinstance(e, ActionEvent) and e.action.command == "/大纲" for e in action_events)
    assert "StoryConsultant" in text_blob
    assert "双主角女将军从冷宫到朝堂" in text_blob
    assert "第一幕" in text_blob
    assert "第四幕" in text_blob

    answered = [e for e in done_events if e.reason == "answered"]
    assert answered, "expected at least one Done(reason='answered')"
    assert answered[0].payload is not None
    assert answered[0].payload.get("outline") is True
    assert answered[0].payload.get("chapter_count") == 4


def test_engine_streams_workflow_stub_chunks() -> None:
    """``start_workflow`` must dispatch to a registered workflow stub and stream its output."""
    deps = production_deps()

    events = _consume(run_engine(_ctx("/写 1.3"), deps))

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))

    assert "[workflow] 占位: write_chapter" in text_blob
    assert "Plan-Execute-Review" in text_blob
    assert any(isinstance(e, Done) and e.reason == "workflow_pending" for e in events)


def test_engine_workflow_unknown_name_yields_explanatory_chunk() -> None:
    """Unknown workflow names should produce a visible explanatory chunk, not silently fail."""
    from dataclasses import replace
    from writer.engine.deps import _DefaultEngineDeps
    from writer.routing import RuleBasedIntentRouter
    from writer.roles import StoryConsultant
    from writer.config import get_settings

    deps = _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        story_consultant=StoryConsultant(get_settings()),
        _workflows={},
    )

    chunks = list(deps.run_workflow("not_a_real_workflow", _ctx("ignored")))

    assert len(chunks) == 1
    assert "未知工作流" in chunks[0]
    assert "not_a_real_workflow" in chunks[0]


def test_production_deps_includes_all_registered_workflows() -> None:
    """production_deps() must register every workflow in writer.workflows.WORKFLOWS."""
    from writer.workflows import WORKFLOWS

    deps = production_deps()

    for name in WORKFLOWS:
        chunks = list(deps.run_workflow(name, _ctx("ignored")))
        assert chunks, f"workflow {name!r} produced no chunks"
