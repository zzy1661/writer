"""Dependency injection boundary for the agent engine.

The engine never instantiates its collaborators directly — every external
boundary is declared here as a ``Protocol``. This matches Claude Code §十
"最小接口 DI": we only inject what gets swapped (tests, alternate routers,
future LLM-backed implementations).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from writer.config import Settings, get_settings
from writer.roles import StoryConsultant
from writer.routing import (
    AgentAction,
    CompositeRouter,
    IntentRouter,
    LlmIntentRouter,
    RuleBasedIntentRouter,
)
from writer.tools import ToolRegistry, ToolRuntime, built_tool_registry
from writer.workflows import WORKFLOWS, WorkflowStub

if TYPE_CHECKING:
    from writer.engine.context import EngineContext

# Sentinel project_root used when no project is initialized (S0 path).
# Tools that need file access will fail their safe_path check; tools that
# don't (foreshadow_query, chapter_locate, wordcount) still work.
_NO_PROJECT_ROOT = Path("/__no_project__")


@runtime_checkable
class EngineDeps(Protocol):
    """Minimum surface the engine loop depends on.

    Current fields:

    * :attr:`router` — front-desk dispatcher (per 备忘 15; Protocol
      :class:`writer.routing.IntentRouter`).
    * :attr:`story_consultant` — the role that handles short creative
      commands such as ``/大纲`` (per 备忘 04).
    * :attr:`tool_registry` — :class:`writer.tools.ToolRegistry` for
      resolving tool names to implementations (per 备忘 13).
    * :attr:`tool_runtime` — :class:`writer.tools.ToolRuntime` carrying
      per-session guards handed to every tool invocation.

    Future expansion points (intentionally not declared yet):
    * ``workflow_starter``: richer async workflow entrypoint
      (per 备忘 04; the current sync ``run_workflow`` is the MVP bridge)
    * ``interrupt_handler``: InterruptHandler (per 备忘 14)
    * ``stop_hooks``: StopHookRegistry (Claude Code §十二·12.3)
    """

    router: IntentRouter
    story_consultant: StoryConsultant
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime

    def route(self, user_input: str, project_state: str) -> AgentAction:
        ...

    def run_workflow(self, name: str, ctx: EngineContext) -> Iterable[str]:
        ...


@dataclass
class _DefaultEngineDeps:
    """Production wiring with the rule-based router and stock workflows.

    Defined as a dataclass rather than a hand-written class so adding
    fields later (tool registry, real workflow starter, …) is a one-line
    change instead of a constructor rewrite.
    """

    router: IntentRouter
    story_consultant: StoryConsultant
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    _workflows: dict[str, WorkflowStub] = field(default_factory=dict)

    def route(self, user_input: str, project_state: str) -> AgentAction:
        return self.router.route(user_input, project_state)

    def run_workflow(self, name: str, ctx: EngineContext) -> Iterable[str]:
        runner = self._workflows.get(name)
        if runner is None:
            return [
                f"[workflow] 未知工作流 {name!r}（占位 stub: {sorted(self._workflows)}）"
            ]
        return runner(ctx)


def _select_router(settings: Settings) -> IntentRouter:
    """Return ``CompositeRouter`` when API key is configured, else bare rule router."""

    if settings.has_api_key:
        return CompositeRouter(
            primary=RuleBasedIntentRouter(),
            fallback=LlmIntentRouter(settings),
        )
    return RuleBasedIntentRouter()


def production_deps(
    settings: Settings | None = None,
    *,
    project_root: Path | None = None,
) -> EngineDeps:
    """Default dependency wiring used by the REPL and tests.

    Tests can pass an explicit :class:`writer.config.Settings` to avoid
    the global settings lookup; production callers (REPL, CLI) leave it
    ``None`` to fall back to :func:`writer.config.get_settings`.

    Args:
        settings: Override for global settings (mainly for tests).
        project_root: Optional override for the tool runtime's root. When
            ``None`` (the S0 path), a sentinel root is used so
            ``safe_path`` still rejects escapes; path-free tools
            (``foreshadow_query`` etc.) keep working.
    """

    resolved = settings if settings is not None else get_settings()
    root = (project_root or _NO_PROJECT_ROOT).resolve()
    return _DefaultEngineDeps(
        router=_select_router(resolved),
        story_consultant=StoryConsultant(resolved),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=root),
        _workflows=dict(WORKFLOWS),
    )


__all__ = ["EngineDeps", "production_deps"]
