"""Tests for ``ContinueWritingSkill`` — the ``/续写`` placeholder."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from writer.engine.context import EngineContext
from writer.engine.deps import _DefaultEngineDeps
from writer.engine.events import Done, TextChunk
from writer.project import ProjectState, create_workspace
from writer.skills import ContinueWritingSkill, built_skill_registry

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig


def test_continue_writing_skill_has_metadata() -> None:
    skill = ContinueWritingSkill()

    assert skill.command == "/续写"
    assert skill.description == "继续未完成章节"
    assert skill.requires_states == frozenset({ProjectState.WRITING})


def test_continue_writing_skill_is_registered() -> None:
    """``/续写`` must show up in the built registry (as a ``ContinueWritingSkill`` instance)."""

    registry = built_skill_registry()
    registered = registry.get("/续写")
    assert isinstance(registered, ContinueWritingSkill)


def test_continue_writing_skill_yields_placeholder_events(tmp_path: Path) -> None:
    """Running the placeholder emits a TODO ``TextChunk`` + ``Done(command_pending)``.

    Mirrors the contract of the future LLM-backed implementation so the
    REPL wiring keeps working unchanged when the real logic lands.
    """

    import asyncio

    workspace = create_workspace("continue-writing", tmp_path)
    deps = _make_deps(workspace.root)
    skill = ContinueWritingSkill()
    ctx = EngineContext(
        user_input="/续写",
        project_root=workspace.root,
        project_state=ProjectState.WRITING.value,
        session_id="t",
    )

    events: list[object] = []

    async def drain() -> None:
        gen: AsyncIterator[TextChunk | Done] = skill.run(ctx, deps, _fast_cfg())
        async for event in gen:
            events.append(event)

    asyncio.run(drain())

    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected at least one Done"
    assert done_events[-1].reason == "command_pending"
    assert done_events[-1].payload is not None
    assert done_events[-1].payload["command"] == "/续写"
    assert done_events[-1].payload["todo"] == "continue_chapter"

    text = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "尚未实现" in text
    assert "LLM" in text


def test_continue_writing_skill_required_states_match_state_matrix(tmp_path: Path) -> None:
    """``/续写`` should only be available in WRITING (S4); the registry
    must reflect this so ``validate_command_available`` rejects it
    elsewhere."""

    registry = built_skill_registry()
    matrix = registry.state_matrix()
    assert matrix["/续写"] == ContinueWritingSkill().requires_states


def test_continue_writing_skill_fast_mode_suppresses_engine_log(tmp_path: Path) -> None:
    """``fast_mode=True`` suppresses the diagnostic ``[engine]`` chunk but
    keeps the TODO and ``Done`` events."""

    import asyncio

    workspace = create_workspace("continue-writing-fast", tmp_path)
    skill = ContinueWritingSkill()
    ctx = EngineContext(
        user_input="/续写",
        project_root=workspace.root,
        project_state=ProjectState.WRITING.value,
        session_id="t",
    )

    events: list[object] = []

    async def drain() -> None:
        async for event in skill.run(
            ctx,
            _make_deps(workspace.root),
            _fast_cfg(fast=True),
        ):
            events.append(event)

    asyncio.run(drain())

    text_events = [e for e in events if isinstance(e, TextChunk)]
    assert all("[engine]" not in e.text for e in text_events)
    assert any(isinstance(e, Done) for e in events)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_deps(project_root: Path | None) -> _DefaultEngineDeps:
    """Build a minimal ``_DefaultEngineDeps`` for invocation tests."""

    from writer.config import get_settings
    from writer.roles import StoryConsultant
    from writer.routing import RuleBasedIntentRouter
    from writer.tools import ToolRuntime, built_tool_registry

    return _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        story_consultant=StoryConsultant(get_settings()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=project_root or Path("/__no_project__")),
        skill_registry=built_skill_registry(),
    )


def _fast_cfg(*, fast: bool = False) -> EngineConfig:
    from writer.engine.config import EngineConfig

    return EngineConfig(session_id="t", fast_mode=fast)
