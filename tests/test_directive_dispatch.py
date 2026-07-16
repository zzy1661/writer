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

from writer.llm.prose import DeterministicProseClient
from writer.project import create_workspace, detect_state
from writer.routing import AgentAction
from writer.runner import (
    Done,
    Runner,
    RunnerContext,
    TextChunk,
    run_runner,
)
from writer.runner.config import build_runner_config
from writer.runner.deps import RunnerDeps
from writer.skills import (
    SkillDirective,
    built_directive_registry,
)
from writer.skills.directive_discovery import resolve_references
from writer.workflows.types import WorkflowResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from writer.runner.context import RunnerContext
    from writer.runner.deps import RunnerDeps
    from writer.runner.events import Done, TextChunk


def _directive(
    command: str = "/test",
    description: str = "test",
    body: str = "body",
    references: dict[str, str] | None = None,
) -> SkillDirective:
    return SkillDirective(
        command=command,
        description=description,
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
        # PR2: ``deps.prose_client`` is a new Protocol field; the rule-
        # only directive path doesn't touch it but the stub still needs
        # the attribute so the engine's isinstance check passes.
        prose_client = DeterministicProseClient()

    runner = Runner(
        deps=_StubDeps(),  # type: ignore[arg-type]
        cfg=build_runner_config(RunnerContext(user_input="/x")),
    )
    async for event in runner._run_directive(
        directive,
        RunnerContext(user_input="/x", project_root=None),
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
    runner = Runner(
        deps=type("_StubDeps", (), {"tool_loop": None})(),  # type: ignore[arg-type]
        cfg=build_runner_config(RunnerContext(user_input="/x")),
    )
    async for event in runner._run_directive(
        directive,
        RunnerContext(user_input="/x"),
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
            run_runner(
                RunnerContext(
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


def _run_runner_sync(ctx: RunnerContext, deps: RunnerDeps) -> list:
    import asyncio

    async def _consume(aiter: AsyncIterator) -> list:
        out = []
        async for ev in aiter:
            out.append(ev)
        return out

    return asyncio.run(_consume(run_runner(ctx, deps)))


def test_dispatch_directive_in_s4_does_not_block(tmp_path: Path) -> None:
    """`/大纲` reaches the directive body in a mid-book S4 project.

    Per chg-remove-state-machine-enforcement: the engine no longer
    gates directives by lifecycle state. In S4 (manuscript has
    chapters) the writer must be able to revise the outline, so
    ``/大纲`` must NOT abort — it enters the directive body and the LLM
    decides append vs overwrite from the actual file state.
    """
    from writer.project.state import ProjectState

    workspace = create_workspace("s4-outline", tmp_path)
    (workspace.root / "大纲" / "大纲.md").write_text("旧大纲", encoding="utf-8")
    (workspace.root / "草稿" / "chapter-01.md").write_text(
        "正文", encoding="utf-8"
    )
    assert detect_state(workspace.root) == ProjectState.WRITING

    deps = _stub_deps(workspace.root)
    events = _run_runner_sync(
        RunnerContext(
            user_input="/大纲 扩写反派动机线",
            project_root=workspace.root,
            project_state="S4",
        ),
        deps,
    )

    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected a terminal Done event"
    assert done_events[0].reason == "answered"
    assert done_events[0].payload.get("directive") == "/大纲"
    assert not any(e.reason == "aborted" for e in done_events)


def test_dispatch_directive_in_s4_does_not_block_toc(tmp_path: Path) -> None:
    """`/目录` reaches the directive body in a mid-book S4 project."""
    from writer.project.state import ProjectState

    workspace = create_workspace("s4-toc", tmp_path)
    (workspace.root / "大纲" / "大纲.md").write_text("旧大纲", encoding="utf-8")
    (workspace.root / "大纲" / "章节目录.md").write_text("第一章", encoding="utf-8")
    (workspace.root / "草稿" / "chapter-01.md").write_text(
        "正文", encoding="utf-8"
    )
    assert detect_state(workspace.root) == ProjectState.WRITING

    deps = _stub_deps(workspace.root)
    events = _run_runner_sync(
        RunnerContext(
            user_input="/目录 把反派觉醒卷加入",
            project_root=workspace.root,
            project_state="S4",
        ),
        deps,
    )

    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected a terminal Done event"
    assert done_events[0].reason == "answered"
    assert done_events[0].payload.get("directive") == "/目录"
    assert not any(e.reason == "aborted" for e in done_events)


def test_engine_dispatches_character_skill(tmp_path: Path) -> None:
    """`/人物` reaches the directive body via ``built_directive_registry``.

    The shipped ``/人物`` SKILL.md (per 2026-07-16 landing) must be
    discoverable without any project root and the engine must route the
    command through ``deps.directive_registry`` (no engine/ code
    changes — the lookup is dynamic per
    ``engine/engine.py:213-215``). With rule-only deployment the
    preview path yields TextChunks + ``Done(reason='answered',
    payload={'directive': '/人物'})``.
    """
    from writer.skills import built_directive_registry

    # 1. directive_registry picks up /人物 shipped even without project root.
    registry = built_directive_registry(project_root=None)
    directive = registry.get("/人物")
    assert directive is not None, "/人物 must be shipped"
    assert "character-card-template.md" in set(
        directive.references or {}
    ), "shipped /人物 must reference character-card-template.md"

    # 2. router captures the slash command.
    from writer.routing import RuleBasedIntentRouter

    action = RuleBasedIntentRouter().route("/人物 张三", _project_state="S5")
    assert action.command == "/人物"
    assert action.action_type == "run_command"

    # 3. engine dispatches to _run_directive (rule-only preview).
    workspace = create_workspace("character-skill", tmp_path)
    deps = _stub_deps(workspace.root)
    events = _run_runner_sync(
        RunnerContext(
            user_input="/人物 张三 主角 25 岁 程序员",
            project_root=workspace.root,
        ),
        deps,
    )

    done_events = [e for e in events if isinstance(e, Done)]
    assert done_events, "expected a terminal Done event"
    answered = [e for e in done_events if e.reason == "answered"]
    assert answered, "expected Done(reason='answered') from rule-only preview"
    assert answered[0].payload.get("directive") == "/人物"
    assert not any(e.reason == "aborted" for e in done_events)


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


def _stub_deps(project_root: Path) -> RunnerDeps:
    """Build an ``RunnerDeps`` stub suitable for ``run_runner``.

    Reuses ``built_directive_registry(project_root=...)`` so the
    engine's directive lookup reflects the project's seeded
    SKILL.md packages.

    Updated 2026-07-09 (``chg-remove-roles``): ``story_agent`` /
    ``rebind_story_agent`` removed — the ``writer.roles.StoryAgent``
    class is gone.
    """
    from writer.agents import builtin_agent_registry
    from writer.routing import RuleBasedIntentRouter
    from writer.tools import ToolRuntime, built_tool_registry

    class _Deps:
        def __init__(self) -> None:
            self.router = RuleBasedIntentRouter()
            self.agent_registry = builtin_agent_registry()
            self.tool_registry = built_tool_registry()
            self.tool_runtime = ToolRuntime(project_root=project_root)
            self.directive_registry = built_directive_registry(
                project_root=project_root
            )
            self.tool_loop = None
            # PR2: ``deps.prose_client`` is a new Protocol field.
            self.prose_client = DeterministicProseClient()

        def route(self, user_input: str, project_state: str) -> AgentAction:
            return self.router.route(user_input, project_state)

        def run_workflow(self, name: str, ctx: RunnerContext) -> WorkflowResult:
            # PR1: return a real WorkflowResult. The dispatcher test
            # only cares that the workflow path is exercised, not the
            # status (the engine emits ``workflow_completed`` after).
            return WorkflowResult(status="completed", chunks=())

        def rebind_tool_runtime(self, new_runtime):
            self.tool_runtime = new_runtime
            return self

        def rebind_directive_registry(self, new_registry):
            self.directive_registry = new_registry
            return self

        def rebind_skill_registry(self, new_registry):
            self.directive_registry = new_registry
            return self

        def rebind_agent_registry(self, new_registry):
            self.agent_registry = new_registry
            return self

    return _Deps()
