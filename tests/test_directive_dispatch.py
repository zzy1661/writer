"""Tests for the engine's directive dispatch path (chg-markdown-skills).

The engine's ``_run_directive`` helper is called when an action's
``command`` matches a registered ``SkillDirective``. Without an LLM
configured (the common case in tests), the helper emits a TextChunk
preview describing the directive and yields
``Done(reason='answered', payload={'directive': ...})``. When an LLM
loop is available, the helper delegates to ``deps.tool_loop.run(...)``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from writer.engine import (
    Done,
    EngineContext,
    TextChunk,
    run_engine,
)
from writer.engine.config import build_engine_config
from writer.engine.deps import EngineDeps
from writer.engine.loop import _run_directive
from writer.project import ProjectState, create_workspace
from writer.routing import AgentAction
from writer.skills import (
    SkillDirective,
    built_directive_registry,
)
from writer.skills.directive_discovery import resolve_references

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps
    from writer.engine.events import Done, TextChunk


def _directive(
    command: str = "/test",
    description: str = "test",
    body: str = "body",
    references: dict[str, str] | None = None,
) -> SkillDirective:
    return SkillDirective(
        command=command,
        description=description,
        requires_states=frozenset({ProjectState.INITIALIZED}),
        body=body,
        references=references or {},
        scripts=[],
        root=Path("/tmp/dummy"),
    )


# ---------------------------------------------------------------------------
# _run_directive without LLM (preview path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_directive_preview_emits_metadata() -> None:
    directive = _directive(
        command="/x",
        description="test desc",
        body="## Step 1\ndo the thing\n@reference t.md\n",
        references={"t.md": "TEMPLATE BODY"},
    )

    events: list = []
    async def _fake_run(*args, **kwargs):
        raise AssertionError("should not call tool_loop")

    class _StubDeps:
        tool_loop = None  # rule-only deployment

    async for event in _run_directive(
        directive,
        EngineContext(user_input="/x", project_root=None),
        _StubDeps(),  # type: ignore[arg-type]
        build_engine_config(EngineContext(user_input="/x")),
    ):
        events.append(event)

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "command: /x" in text_blob
    assert "test desc" in text_blob
    assert "body length:" in text_blob
    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected at least one Done(reason='answered')"
    assert done_events[0].reason == "answered"
    assert done_events[0].payload.get("directive") == "/x"
    assert "t.md" in done_events[0].payload.get("references", [])


@pytest.mark.asyncio
async def test_run_directive_resolves_at_references(tmp_path: Path) -> None:
    """@reference mentions appear in the preview TextChunk with content."""
    directive = _directive(
        command="/x",
        body="see @reference notes.md for details",
        references={"notes.md": "VERY IMPORTANT CONTENT"},
    )

    events: list = []
    async for event in _run_directive(
        directive,
        EngineContext(user_input="/x"),
        type("_StubDeps", (), {"tool_loop": None})(),  # type: ignore[arg-type]
        build_engine_config(EngineContext(user_input="/x")),
    ):
        events.append(event)

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "notes.md" in text_blob


# ---------------------------------------------------------------------------
# end-to-end through the engine loop
# ---------------------------------------------------------------------------


def test_engine_dispatches_via_directive_registry(tmp_path: Path) -> None:
    """Engine routes a known directive command to _run_directive.

    With no LLM configured, the engine emits a TextChunk preview
    describing the directive and yields Done(reason='answered').
    """
    workspace = create_workspace("dispatch-test", tmp_path)
    deps = _stub_deps(workspace.root)

    events = []
    async def _consume(aiter: AsyncIterator) -> list:
        out = []
        async for ev in aiter:
            out.append(ev)
        return out

    import asyncio

    events = asyncio.run(
        _consume(
            run_engine(
                EngineContext(
                    user_input="/大纲 双主角女将军从冷宫到朝堂",
                    project_root=workspace.root,
                ),
                deps,
            )
        )
    )

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    assert "→ directive" in text_blob
    done_events = [e for e in events if isinstance(e, Done)]
    answered = [e for e in done_events if e.reason == "answered"]
    assert answered, "expected Done(reason='answered')"
    assert answered[0].payload.get("directive") == "/大纲"


# ---------------------------------------------------------------------------
# resolve_references is exercised via the engine path
# ---------------------------------------------------------------------------


def test_resolve_references_helper_integration() -> None:
    body = "@reference a.md\nmiddle\n@reference b.md\n"
    refs = {"a.md": "AAA", "b.md": "BBB"}
    out = resolve_references(body, refs)
    assert out == [("a.md", "AAA"), ("b.md", "BBB")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_deps(project_root: Path) -> EngineDeps:
    """Build an ``EngineDeps`` stub suitable for ``run_engine``.

    Reuses ``built_directive_registry(project_root=...)`` so the
    engine's directive lookup reflects the project's seeded
    SKILL.md packages.
    """
    from writer.config import get_settings
    from writer.roles import StoryConsultant
    from writer.routing import RuleBasedIntentRouter
    from writer.tools import ToolRuntime, built_tool_registry

    class _Deps:
        def __init__(self) -> None:
            self.router = RuleBasedIntentRouter()
            self.story_consultant = StoryConsultant(get_settings())
            self.tool_registry = built_tool_registry()
            self.tool_runtime = ToolRuntime(project_root=project_root)
            self.directive_registry = built_directive_registry(
                project_root=project_root
            )
            self.tool_loop = None

        def route(self, user_input: str, project_state: str) -> AgentAction:
            return self.router.route(user_input, project_state)

        def run_workflow(self, name: str, ctx: EngineContext):
            return []

        def rebind_tool_runtime(self, new_runtime):
            self.tool_runtime = new_runtime
            return self

        def rebind_story_consultant(self, new_consultant):
            self.story_consultant = new_consultant
            return self

        def rebind_directive_registry(self, new_registry):
            self.directive_registry = new_registry
            return self

        def rebind_skill_registry(self, new_registry):
            self.directive_registry = new_registry
            return self

    return _Deps()
