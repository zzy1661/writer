"""Tests for dynamic engine dispatch through the Skill registry.

Coverage:
* registry.get() → skill.run() through ``_engine_loop`` with no engine
  changes (the dispatch is data-driven)
* a slash command that maps to a Skill gets the ``skill_registry`` log
  line and yields the Skill's ``TextChunk`` / ``Done`` events
* a slash command without a registered Skill still falls back to the
  ``command_pending`` terminal branch
* the engine boundary treats ``SkillError`` like ``ToolError`` —
  surfaces as ``ErrorEvent`` + ``Done(aborted, payload={'command': ...})``
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from writer.engine import (
    ActionEvent,
    Done,
    EngineContext,
    ErrorEvent,
    TextChunk,
    production_deps,
    run_engine,
)
from writer.engine.config import EngineConfig
from writer.engine.context import EngineContext as Ctx
from writer.engine.deps import _DefaultEngineDeps
from writer.project import ProjectState, create_workspace, detect_state
from writer.roles import StoryConsultant
from writer.routing import AgentAction
from writer.skills import Skill, SkillError, built_skill_registry
from writer.skills.outline import OutlineSkill
from writer.tools import ToolRuntime, built_tool_registry

if TYPE_CHECKING:
    from writer.config import Settings
    from writer.engine.deps import EngineDeps


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _GreetingSkill:
    """Minimal custom skill used to prove the engine routes a new slash
    command through the registry without any engine changes."""

    command = "/greet"
    description = "示例：测试动态 dispatch"
    requires_states = frozenset({ProjectState.INITIALIZED, ProjectState.HAS_OUTLINE})

    async def run(
        self,
        ctx: Ctx,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        from writer.engine.events import Done as _Done
        from writer.engine.events import TextChunk as _TextChunk

        del ctx
        del deps
        if not cfg.fast_mode:
            yield _TextChunk(text="[engine] /greet → greeting skill\n")
        yield _TextChunk(text="hello from a plugin skill\n")
        yield _Done(reason="answered", payload={"command": self.command})


class _FailingSkill:
    """Skill that always raises ``SkillError`` so we can test the engine
    boundary code path. The first ``yield`` makes ``run()`` a real async
    generator; the raise happens on the first ``__anext__`` so the engine
    catches it the same way it catches any other exception raised inside
    a Skill body."""

    command = "/kaboom"
    description = "示例：抛 SkillError"
    requires_states = frozenset({ProjectState.INITIALIZED})

    async def run(
        self,
        ctx: Ctx,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        del ctx
        del deps
        del cfg
        # ``yield`` once so this is an async generator function; the
        # engine iterates via ``async for`` (see loop.py).
        yield TextChunk(text="[engine] /kaboom → about to raise\n")
        msg = "intentional skill failure"
        raise SkillError(msg)


class _FixedRouter:
    """Stand-in router that returns a fixed run_command action."""

    def __init__(self, command: str, action_type: str = "run_command") -> None:
        self._command = command
        self._action_type = action_type

    def route(self, user_input: str, project_state: str) -> AgentAction:
        return AgentAction(action_type=self._action_type, command=self._command)


def _consume(events: AsyncIterator[object]) -> list[object]:
    import asyncio

    async def drain() -> list[object]:
        return [event async for event in events]

    return asyncio.run(drain())


def _workspace_ctx(text: str, root: Path) -> EngineContext:
    return EngineContext(
        user_input=text,
        project_root=root,
        project_state=detect_state(root).value,
        session_id="test",
    )


# ---------------------------------------------------------------------------
# Dispatch is data-driven
# ---------------------------------------------------------------------------


def test_outline_skill_still_routes_via_registry(tmp_path: Path) -> None:
    """``/大纲`` still works after refactor — registers through registry,
    dispatches through ``skill_registry.get(action.command)``."""

    workspace = create_workspace("dispatch-outline", tmp_path)
    deps = production_deps(project_root=workspace.root)

    events = _consume(
        run_engine(_workspace_ctx("/大纲 测试创意", workspace.root), deps)
    )

    text = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "outline skill" in text
    done_events = [e for e in events if isinstance(e, Done)]
    assert any(e.reason == "answered" for e in done_events)


def test_toc_skill_still_routes_via_registry(tmp_path: Path) -> None:
    """``/目录`` still routes through ``skill_registry.get('/目录')``."""

    workspace = create_workspace("dispatch-toc", tmp_path)
    (workspace.root / "outline" / "大纲.md").write_text(
        "# 测试书名\n\n## 四幕\n\n- 一\n- 二\n- 三\n- 四\n",
        encoding="utf-8",
    )
    deps = production_deps(project_root=workspace.root)

    events = _consume(run_engine(_workspace_ctx("/目录", workspace.root), deps))

    text = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "toc skill" in text
    assert (workspace.root / "outline" / "toc.md").is_file()


def test_unknown_command_falls_through_to_command_pending(tmp_path: Path) -> None:
    """Slash commands without a Skill still hit the ``command_pending`` branch."""

    workspace = create_workspace("dispatch-unknown", tmp_path)

    deps = _DefaultEngineDeps(
        router=_FixedRouter("/some-unknown-command"),  # type: ignore[arg-type]
        story_consultant=StoryConsultant(_settings_for_test()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=workspace.root),
        skill_registry=built_skill_registry(),
    )

    events = _consume(
        run_engine(_workspace_ctx("/some-unknown-command", workspace.root), deps)
    )

    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events[-1].reason == "command_pending"
    assert done_events[-1].payload is not None
    assert done_events[-1].payload["command"] == "/some-unknown-command"


def test_dispatch_picks_up_custom_skill_added_to_registry(tmp_path: Path) -> None:
    """Injecting a new Skill into the registry is enough — no engine changes."""

    workspace = create_workspace("dispatch-custom", tmp_path)

    # Build a registry that includes a plugin skill alongside built-ins.
    registry = built_skill_registry()  # type: ignore[assignment]
    # The built registry is immutable from the outside, so call the factory
    # path that allows extras (per registry.py: skills + extra_skills).
    from writer.skills.registry import SkillRegistry

    registry = SkillRegistry(
        skills=list(registry._by_command.values()) + [_GreetingSkill()],  # type: ignore[arg-type]
    )

    deps = _DefaultEngineDeps(
        router=_FixedRouter("/greet"),  # type: ignore[arg-type]
        story_consultant=StoryConsultant(_settings_for_test()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=workspace.root),
        skill_registry=registry,
    )

    events = _consume(
        run_engine(_workspace_ctx("/greet", workspace.root), deps)
    )

    text = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "greeting skill" in text
    assert "hello from a plugin skill" in text
    assert any(isinstance(e, ActionEvent) for e in events)
    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events[-1].reason == "answered"
    assert done_events[-1].payload is not None
    assert done_events[-1].payload["command"] == "/greet"


# ---------------------------------------------------------------------------
# SkillError boundary handling
# ---------------------------------------------------------------------------


def test_engine_surfaces_skill_error_as_error_event_plus_aborted(tmp_path: Path) -> None:
    """A Skill raising ``SkillError`` must be caught at the engine boundary
    and surfaced via the same shape as ``ToolError`` → ``ErrorEvent`` +
    ``Done(aborted, payload={..., 'command': ...})``."""

    workspace = create_workspace("dispatch-skill-error", tmp_path)

    from writer.skills.registry import SkillRegistry

    registry = SkillRegistry(
        skills=list(built_skill_registry()._by_command.values()) + [_FailingSkill()],  # type: ignore[arg-type]
    )

    deps = _DefaultEngineDeps(
        router=_FixedRouter("/kaboom"),  # type: ignore[arg-type]
        story_consultant=StoryConsultant(_settings_for_test()),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=workspace.root),
        skill_registry=registry,
    )

    events = _consume(
        run_engine(_workspace_ctx("/kaboom", workspace.root), deps)
    )

    assert any(
        isinstance(e, ErrorEvent) and "intentional skill failure" in e.message
        for e in events
    )
    aborted = [e for e in events if isinstance(e, Done) and e.reason == "aborted"]
    assert aborted, "expected Done(reason='aborted')"
    assert aborted[-1].payload is not None
    assert aborted[-1].payload["command"] == "/kaboom"
    assert "intentional skill failure" in str(aborted[-1].payload["error"])


# ---------------------------------------------------------------------------
# Validation: state matrix consults the registry
# ---------------------------------------------------------------------------


def test_state_matrix_blocks_skill_command_in_wrong_state(tmp_path: Path) -> None:
    """``/续写`` requires WRITING — running it on a fresh S1 project must be
    rejected by the engine's state-matrix guard, not by the skill body.

    Demonstrates that ``validate_command_available`` is now driven by
    ``skill_registry.state_matrix()``.
    """

    workspace = create_workspace("dispatch-state-block", tmp_path)
    # S1 (no outline, no manuscript) — /续写 must be blocked.
    deps = production_deps(project_root=workspace.root)

    events = _consume(
        run_engine(_workspace_ctx("/续写", workspace.root), deps)
    )

    text = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "/续写 当前不可用" in text
    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events[-1].reason == "aborted"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _settings_for_test() -> Settings:
    from writer.config import get_settings

    return get_settings()


def test_skill_protocol_metadata_satisfies_outline_skill() -> None:
    """Defensive: our registry is consistent with the Protocol metadata
    contract — basically a smoke test that OutlineSkill got the new fields."""

    skill = OutlineSkill()
    assert skill.command == "/大纲"
    assert isinstance(skill.description, str)
    assert skill.requires_states
    assert ProjectState.INITIALIZED in skill.requires_states
    assert isinstance(skill, Skill)


@pytest.fixture
def settings() -> Settings:
    from writer.config import get_settings

    return get_settings()


# Inherit the ``_ctx`` helper used by other engine tests if present
def _ctx(  # type: ignore[no-untyped-def]
    text: str,
    *,
    project_root: Path | None = None,
    project_state: str = "S0",
) -> EngineContext:
    return EngineContext(
        user_input=text,
        project_root=project_root,
        project_state=project_state,
        session_id="test",
    )
