"""Dependency injection boundary for the agent engine.

The engine never instantiates its collaborators directly — every external
boundary is declared here as a ``Protocol``. This matches Claude Code §十
"最小接口 DI": we only inject what gets swapped (tests, alternate routers,
future LLM-backed implementations).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
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
from writer.tools.errors import WorkflowNotFoundError
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

    def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the runtime swapped.

        Called by :meth:`writer.session.EngineSession.set_project_root` to
        point the existing deps at a new project root without rebuilding
        router / story_consultant / tool_registry. Implementations are
        free to return a new instance (default impl uses ``dataclasses
        .replace``) or mutate ``self`` — both are valid as long as the
        returned value is used as the new deps.

        Added 2026-07-05 to fix arch-optimizer M6: the old code
        duck-typed ``is_dataclass(self.deps) and any(f.name == ...)``,
        which broke the moment a test injected a non-dataclass
        ``EngineDeps`` implementation.
        """
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
            # Raised as a domain exception (per arch-optimizer m18) so the
            # engine's ``except ToolError`` branch in ``_engine_loop`` can
            # surface it as an ``ErrorEvent`` instead of pretending the
            # unknown name produced a legitimate workflow chunk.
            available = sorted(self._workflows)
            raise WorkflowNotFoundError(
                f"未知工作流 {name!r}; available: {available}"
            )
        return runner(ctx)

    def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> EngineDeps:
        # Use ``dataclasses.replace`` so the production wiring stays
        # effectively immutable; tests that need mutation can still
        # override the method.
        return replace(self, tool_runtime=new_runtime)


def _select_router(
    settings: Settings,
    *,
    primary: IntentRouter | None = None,
) -> IntentRouter:
    """Return ``CompositeRouter`` when API key is configured, else bare rule router.

    ``primary`` lets callers (esp. tests) inject a custom rule router
    without rewriting this factory; defaults to a fresh
    :class:`RuleBasedIntentRouter`. Added 2026-07-05 per arch-optimizer
    M5: the previous code hard-coded ``RuleBasedIntentRouter()`` inside
    the factory, so a future "RuleBasedIntentRouterV2" would silently
    miss the wiring.
    """

    rule = primary or RuleBasedIntentRouter()
    if settings.has_api_key:
        return CompositeRouter(primary=rule, fallback=LlmIntentRouter(settings))
    return rule


def production_deps(
    settings: Settings | None = None,
    *,
    project_root: Path | None = None,
    primary_router: IntentRouter | None = None,
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
        primary_router: Optional override for the rule router used as
            the primary in the ``CompositeRouter`` (when API key is
            set) or as the bare router (when not). Defaults to a fresh
            :class:`RuleBasedIntentRouter`. Added 2026-07-05 per M5.
    """

    resolved = settings if settings is not None else get_settings()
    root = (project_root or _NO_PROJECT_ROOT).resolve()
    return _DefaultEngineDeps(
        router=_select_router(resolved, primary=primary_router),
        story_consultant=StoryConsultant(resolved),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=root),
        _workflows=dict(WORKFLOWS),
    )


__all__ = ["EngineDeps", "production_deps"]
