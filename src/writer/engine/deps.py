"""Dependency injection boundary for the agent engine.

The engine never instantiates its collaborators directly — every external
boundary is declared here as a ``Protocol``. This matches Claude Code §十
"最小接口 DI": we only inject what gets swapped (tests, alternate routers,
future LLM-backed implementations).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from writer.config import Settings, get_settings
from writer.roles import StoryConsultant
from writer.routing import AgentAction, IntentRouter, RuleBasedIntentRouter
from writer.workflows import WORKFLOWS, WorkflowStub

if TYPE_CHECKING:
    from writer.engine.context import EngineContext


@runtime_checkable
class EngineDeps(Protocol):
    """Minimum surface the engine loop depends on.

    Current fields:

    * :attr:`router` — front-desk dispatcher (per 备忘 15; Protocol
      :class:`writer.routing.IntentRouter`).
    * :attr:`story_consultant` — the role that handles short creative
      commands such as ``/大纲`` (per 备忘 04).

    Future expansion points (intentionally not declared yet):
    * ``tool_registry``: ToolRegistry (per 备忘 13)
    * ``workflow_starter``: richer async workflow entrypoint
      (per 备忘 04; the current sync ``run_workflow`` is the MVP bridge)
    * ``interrupt_handler``: InterruptHandler (per 备忘 14)
    * ``stop_hooks``: StopHookRegistry (Claude Code §十二·12.3)
    """

    router: IntentRouter
    story_consultant: StoryConsultant

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


def production_deps(settings: Settings | None = None) -> EngineDeps:
    """Default dependency wiring used by the REPL and tests.

    Tests can pass an explicit :class:`writer.config.Settings` to avoid
    the global settings lookup; production callers (REPL, CLI) leave it
    ``None`` to fall back to :func:`writer.config.get_settings`.
    """
    resolved = settings if settings is not None else get_settings()
    return _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        story_consultant=StoryConsultant(resolved),
        _workflows=dict(WORKFLOWS),
    )


__all__ = ["EngineDeps", "production_deps"]
