"""Unit tests for the agent engine MVP."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from writer.agent import AgentAction, WriterCommandAgent
from writer.engine import (
    ActionEvent,
    Done,
    EngineContext,
    TextChunk,
    production_deps,
    run_engine,
)
from writer.engine.deps import EngineDeps


# ---------------------------------------------------------------------------
# Dispatcher classification
# ---------------------------------------------------------------------------


def test_dispatcher_classifies_write_command() -> None:
    action = WriterCommandAgent().decide("/写 1.3", "S0")

    assert action.action_type == "start_workflow"
    assert action.workflow == "write_chapter"
    assert action.role == "story_consultant"
    assert action.command == "/写"


def test_dispatcher_classifies_review_command() -> None:
    action = WriterCommandAgent().decide("/审核 第3章", "S2")

    assert action.action_type == "start_workflow"
    assert action.workflow == "review_chapter"
    assert action.role == "reviewer"
    assert action.command == "/审核"


def test_dispatcher_classifies_tool_query() -> None:
    action = WriterCommandAgent().decide("查一下 F003 伏笔出现位置", "S2")

    assert action.action_type == "call_tool"
    assert action.tool_name == "foreshadow_query"
    assert action.role == "story_consultant"
    assert action.arguments == {"query": "查一下 F003 伏笔出现位置"}


def test_dispatcher_classifies_init_command() -> None:
    action = WriterCommandAgent().decide("/init", "S0")

    assert action.action_type == "run_command"
    assert action.command == "/init"


def test_dispatcher_falls_back_to_answer() -> None:
    action = WriterCommandAgent().decide("帮我润色下这段", "S2")

    assert action.action_type == "answer_directly"
    assert action.answer is not None
    assert "帮我润色下这段" in action.answer


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


def test_production_deps_has_dispatcher() -> None:
    deps = production_deps()

    assert isinstance(deps, EngineDeps)
    assert isinstance(deps.dispatcher, WriterCommandAgent)

    action: AgentAction = deps.decide("/init", "S0")
    assert action.action_type == "run_command"
