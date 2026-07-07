"""Tests for ``ReviseSkill`` — the ``/改`` placeholder."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from writer.engine.context import EngineContext
from writer.engine.deps import _DefaultEngineDeps
from writer.engine.events import Done, TextChunk
from writer.project import ProjectState, create_workspace
from writer.skills import ReviseSkill, built_skill_registry

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig


def test_revise_skill_has_metadata() -> None:
    skill = ReviseSkill()

    assert skill.command == "/改"
    assert skill.description == "修改章节内容"
    assert skill.requires_states == frozenset({ProjectState.WRITING})


def test_revise_skill_is_registered() -> None:
    registry = built_skill_registry()
    registered = registry.get("/改")
    assert isinstance(registered, ReviseSkill)


def test_revise_skill_yields_placeholder_events(tmp_path: Path) -> None:
    """Same shape as ``/续写`` (placeholder emits TODO + ``command_pending``).

    The actual revision LLM pipeline will replace the body but keep the
    event stream so the CLI does not need to change.
    """

    import asyncio

    workspace = create_workspace("revise", tmp_path)
    skill = ReviseSkill()
    ctx = EngineContext(
        user_input="/改",
        project_root=workspace.root,
        project_state=ProjectState.WRITING.value,
        session_id="t",
    )

    events: list[object] = []

    async def drain() -> None:
        async for event in skill.run(ctx, _make_deps(workspace.root), _fast_cfg()):
            events.append(event)

    asyncio.run(drain())

    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected at least one Done"
    assert done_events[-1].reason == "command_pending"
    assert done_events[-1].payload is not None
    assert done_events[-1].payload["command"] == "/改"
    assert done_events[-1].payload["todo"] == "revise_chapter"

    text = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "尚未实现" in text
    assert "LLM" in text


def test_revise_skill_required_states_match_state_matrix(tmp_path: Path) -> None:
    """``/改`` is also WRITING-only."""

    registry = built_skill_registry()
    matrix = registry.state_matrix()
    assert matrix["/改"] == ReviseSkill().requires_states


# ---------------------------------------------------------------------------
# helpers (mirror test_continue_writing_skill.py)
# ---------------------------------------------------------------------------


def _make_deps(project_root: Path | None) -> _DefaultEngineDeps:
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


def _fast_cfg() -> EngineConfig:
    from writer.engine.config import EngineConfig

    return EngineConfig(session_id="t", fast_mode=False)
