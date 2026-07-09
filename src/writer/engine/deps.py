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

from writer.agents import AgentRegistry, built_agent_registry
from writer.config import Settings, get_settings
from writer.roles import (
    HistoryAgent,
    RomanceAgent,
    StoryAgent,
    XuanhuanAgent,
)
from writer.routing import (
    AgentAction,
    CompositeRouter,
    IntentRouter,
    LlmIntentRouter,
    RuleBasedIntentRouter,
)
from writer.skills import DirectiveRegistry, built_directive_registry
from writer.tools import ToolRegistry, ToolRuntime, built_tool_registry
from writer.tools.errors import WorkflowNotFoundError
from writer.workflows import WORKFLOWS, WorkflowStub

if TYPE_CHECKING:
    from writer.engine.context import EngineContext
    from writer.llm.agent import LLMToolLoop

# Sentinel project_root used when no project is initialized (S0 path).
# Tools that need file access will fail their safe_path check; tools that
# don't (foreshadow_search, chapter_locate, wordcount) still work.
_NO_PROJECT_ROOT = Path("/__no_project__")


# Maps the four supported canonical genres onto their Agent classes.
# Anything outside the whitelist (and ``"other"``) falls through to the
# default :class:`StoryAgent` per the ``fea-genre-aware-init`` spec.
_GENRE_AGENT: dict[str, type[StoryAgent]] = {
    "历史": HistoryAgent,
    "言情": RomanceAgent,
    "玄幻": XuanhuanAgent,
}


def _agent_for_genre(
    settings: Settings, genre: str
) -> StoryAgent:
    """Pure factory — pick an Agent subclass by canonical genre key.

    No filesystem IO. Falls back to :class:`StoryAgent` for unknown,
    empty, or ``"other"`` values. Used by both ``production_deps`` and
    :meth:`writer.session.EngineSession.set_project_root` (after
    :meth:`refresh_project_genre` has read the AGENT.md ``题材:`` line).

    Added 2026-07-07 to fix arch-optimizer M1: ``EngineSession`` needs
    to rebuild its agent when the bound project changes genre,
    which requires a helper that doesn't re-read AGENT.md (the session
    has already read it). Renamed from ``_consultant_for_genre`` to
    ``_agent_for_genre`` per ``fea-agent-mirror`` (2026-07-09).
    """
    canonical = (genre or "").strip()
    agent_cls = _GENRE_AGENT.get(canonical, StoryAgent)
    return agent_cls(settings)


@runtime_checkable
class EngineDeps(Protocol):
    """Minimum surface the engine loop depends on.

    Current fields:

    * :attr:`router` — front-desk dispatcher (per 备忘 15; Protocol
      :class:`writer.routing.IntentRouter`).
    * :attr:`story_agent` — the role that handles short creative
      commands such as ``/大纲`` (per 备忘 04). Renamed from
      ``story_consultant`` per ``fea-agent-mirror``.
    * :attr:`agent_registry` — :class:`writer.agents.AgentRegistry`
      for resolving agent names to their YAML-loaded definitions.
      Rebuilt on project change via :meth:`rebind_agent_registry`
      (per ``fea-agent-mirror``).
    * :attr:`tool_registry` — :class:`writer.tools.ToolRegistry` for
      resolving tool names to implementations (per 备忘 13).
    * :attr:`tool_runtime` — :class:`writer.tools.ToolRuntime` carrying
      per-session guards handed to every tool invocation.
    * :attr:`tool_loop` — optional ReAct-style LLM tool loop. ``None``
      in rule-only deployments (no API key) so the engine still works
      via ``_run_tool`` with zero LLM calls; populated when the API
      key is configured. Forward-referenced as a string to keep the
      engine package free of direct ``writer.llm.*`` imports.
    * :attr:`directive_registry` — :class:`writer.skills.DirectiveRegistry`
      mapping slash commands to :class:`writer.skills.SkillDirective`
      (Markdown SKILL.md directives). Rebuilt on project change via
      :meth:`rebind_directive_registry` (per ``chg-markdown-skills``).

    Future expansion points (intentionally not declared yet):
    * ``workflow_starter``: richer async workflow entrypoint
      (per 备忘 04; the current sync ``run_workflow`` is the MVP bridge)
    * ``interrupt_handler``: InterruptHandler (per 备忘 14)
    * ``stop_hooks``: StopHookRegistry (Claude Code §十二·12.3)
    """

    router: IntentRouter
    story_agent: StoryAgent
    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    directive_registry: DirectiveRegistry
    tool_loop: LLMToolLoop | None

    def route(self, user_input: str, project_state: str) -> AgentAction:
        ...

    def run_workflow(self, name: str, ctx: EngineContext) -> Iterable[str]:
        ...

    def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the runtime swapped.
        Called by :meth:`writer.session.EngineSession.set_project_root` to
        point the existing deps at a new project root without rebuilding
        router / story_agent / tool_registry. Implementations are
        free to return a new instance (default impl uses ``dataclasses
        .replace``) or mutate ``self`` — both are valid as long as the
        returned value is used as the new deps.

        Added 2026-07-05 to fix arch-optimizer M6: the old code
        duck-typed ``is_dataclass(self.deps) and any(f.name == ...)``,
        which broke the moment a test injected a non-dataclass
        ``EngineDeps`` implementation.
        """
        ...

    def rebind_story_agent(
        self, new_agent: StoryAgent
    ) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the agent swapped.

        Symmetric to :meth:`rebind_tool_runtime`. Called by
        :meth:`writer.session.EngineSession.set_project_root` after
        :meth:`refresh_project_genre` has read the new project's
        ``AGENT.md`` ``题材:`` line — Agent classes
        (History / Romance / Xuanhuan / Story fallback) are picked at
        construction time, so a genre change requires a fresh
        agent instance.

        Renamed from ``rebind_story_consultant`` per ``fea-agent-mirror``
        (2026-07-09). Symmetric to :meth:`rebind_agent_registry`.
        """
        ...

    def rebind_skill_registry(
        self, new_registry: DirectiveRegistry
    ) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the directive registry swapped.

        Symmetric to :meth:`rebind_tool_runtime` and
        :meth:`rebind_story_agent`. Called by
        :meth:`writer.session.EngineSession.set_project_root` after
        the new project's ``.writer/skills/`` has been scanned — the
        registry MUST be rebuilt on project change so project-level
        directive overrides (per ``chg-markdown-skills``) take effect
        on the next REPL turn.

        Kept as an alias of :meth:`rebind_directive_registry` for
        back-compat with downstream code that still uses the older
        name.

        Added 2026-07-08 alongside the project-skills capability.
        Renamed to :meth:`rebind_directive_registry` on 2026-07-09
        (chg-markdown-skills).
        """
        ...

    def rebind_directive_registry(
        self, new_registry: DirectiveRegistry
    ) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the directive registry swapped.

        Symmetric to :meth:`rebind_tool_runtime` and
        :meth:`rebind_story_agent`. Called by
        :meth:`writer.session.EngineSession.set_project_root` after
        the new project's ``.writer/skills/`` has been scanned — the
        registry MUST be rebuilt on project change so project-level
        directive overrides (per ``chg-markdown-skills``) take effect
        on the next REPL turn.

        Added 2026-07-09 (chg-markdown-skills). The prior
        :meth:`rebind_skill_registry` is preserved as an alias.
        """
        ...

    def rebind_agent_registry(
        self, new_registry: AgentRegistry
    ) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the agent registry swapped.

        Symmetric to :meth:`rebind_directive_registry`. Called by
        :meth:`writer.session.EngineSession.set_project_root` after
        the new project's ``.writer/agents/`` has been scanned — the
        registry MUST be rebuilt on project change so project-level
        agent overrides (per ``fea-agent-mirror``) take effect on
        the next REPL turn.

        Added 2026-07-09 (``fea-agent-mirror``).
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
    story_agent: StoryAgent
    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    directive_registry: DirectiveRegistry
    tool_loop: LLMToolLoop | None = None
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

    def rebind_story_agent(
        self, new_agent: StoryAgent
    ) -> EngineDeps:
        # Symmetric to ``rebind_tool_runtime``; uses ``dataclasses.replace``
        # to keep the production wiring effectively immutable.
        return replace(self, story_agent=new_agent)

    def rebind_skill_registry(
        self, new_registry: DirectiveRegistry
    ) -> EngineDeps:
        # Back-compat alias: per chg-markdown-skills the canonical name
        # is ``rebind_directive_registry`` but older test stubs may
        # still call the older name.
        return replace(self, directive_registry=new_registry)

    def rebind_directive_registry(
        self, new_registry: DirectiveRegistry
    ) -> EngineDeps:
        # Symmetric to ``rebind_tool_runtime`` / ``rebind_story_agent``;
        # uses ``dataclasses.replace`` to keep the production wiring
        # effectively immutable. Per chg-markdown-skills: project-level
        # directives live in the project directory, so this MUST be
        # called whenever the bound project changes.
        return replace(self, directive_registry=new_registry)

    def rebind_agent_registry(
        self, new_registry: AgentRegistry
    ) -> EngineDeps:
        # Symmetric to ``rebind_directive_registry``; uses
        # ``dataclasses.replace`` to keep the production wiring
        # effectively immutable. Per ``fea-agent-mirror``: project-level
        # agents live in the project directory, so this MUST be called
        # whenever the bound project changes.
        return replace(self, agent_registry=new_registry)


def _select_router(
    settings: Settings,
    *,
    primary: IntentRouter | None = None,
    agent_registry: AgentRegistry | None = None,
) -> IntentRouter:
    """Return ``CompositeRouter`` when API key is configured, else bare rule router.

    ``primary`` lets callers (esp. tests) inject a custom rule router
    without rewriting this factory; defaults to a fresh
    :class:`RuleBasedIntentRouter`. Added 2026-07-05 per arch-optimizer
    M5: the previous code hard-coded ``RuleBasedIntentRouter()`` inside
    the factory, so a future "RuleBasedIntentRouterV2" would silently
    miss the wiring.

    ``agent_registry`` (added 2026-07-09 per ``fea-agent-mirror``) is
    forwarded to the LLM router so its system prompt can include the
    list of available agents for parent-LLM dispatch. The rule-based
    router ignores it (rules operate on slash commands only).
    """

    rule = primary or RuleBasedIntentRouter()
    if settings.has_api_key:
        return CompositeRouter(
            primary=rule,
            fallback=LlmIntentRouter(settings, agent_registry=agent_registry),
        )
    return rule


def production_deps(
    settings: Settings | None = None,
    *,
    project_root: Path | None = None,
    primary_router: IntentRouter | None = None,
    agent_registry: AgentRegistry | None = None,
    story_agent: StoryAgent | None = None,
    genre: str = "other",
) -> EngineDeps:
    """Default dependency wiring used by the REPL and tests.

    Pure factory: no filesystem IO behind the caller's back. The
    ``genre`` argument MUST be supplied by the caller — the session
    layer (``EngineSession.__post_init__``) and the CLI
    (``init_project``) are the only two sites that know the project's
    genre, and they read ``AGENT.md`` themselves before delegating
    here. Defaults to ``"other"`` so the simple / S0 paths (tests that
    only care about the deps surface, etc.) keep working without a
    genre lookup.

    Tests can pass an explicit :class:`writer.config.Settings` to avoid
    the global settings lookup; production callers (REPL, CLI) leave it
    ``None`` to fall back to :func:`writer.config.get_settings`.

    Args:
        settings: Override for global settings (mainly for tests).
        project_root: Optional override for the tool runtime's root. When
            ``None`` (the S0 path), a sentinel root is used so
            ``safe_path`` still rejects escapes; path-free tools
            (``foreshadow_search`` etc.) keep working. Also passed
            to :func:`writer.skills.built_skill_registry` so the
            initial skill registry already reflects the bound
            project's ``.writer/skills/`` overrides (per
            ``chg-project-skills``); and to
            :func:`writer.agents.built_agent_registry` for the
            ``.writer/agents/`` layer (per ``fea-agent-mirror``).
        primary_router: Optional override for the rule router used as
            the primary in the ``CompositeRouter`` (when API key is
            set) or as the bare router (when not). Defaults to a fresh
            :class:`RuleBasedIntentRouter`. Added 2026-07-05 per M5.
        agent_registry: Optional override for the agent registry.
            Defaults to :func:`writer.agents.built_agent_registry`
            scoped to ``project_root``. Added 2026-07-09 per
            ``fea-agent-mirror``.
        story_agent: Optional override for the active agent (typically
            a :class:`StoryAgent` / :class:`HistoryAgent` /
            :class:`RomanceAgent` / :class:`XuanhuanAgent`). Defaults
            to :func:`_agent_for_genre` against the passed ``genre``.
        genre: Canonical genre key for picking the Agent subclass
            (one of ``"历史" / "言情 / "玄幻"``, everything else
            falls through to :class:`StoryAgent`). Added 2026-07-08
            to make ``production_deps`` a pure factory (M2 of the
            genre-aware init sprint). Callers that have not yet read
            ``AGENT.md`` should pass ``"other"``.
    """

    resolved = settings if settings is not None else get_settings()
    root = (project_root or _NO_PROJECT_ROOT).resolve()
    tool_registry = built_tool_registry()
    tool_runtime = ToolRuntime(project_root=root)
    tool_loop: LLMToolLoop | None = None
    if resolved.has_api_key:
        # Lazy import so rule-only deployments (no API key) never load
        # the LLM client stack — and so the engine package keeps no
        # runtime dependency on ``writer.llm.agent``. The forward
        # reference in :class:`EngineDeps.tool_loop` keeps mypy happy
        # without importing the module at type-check time either.
        from writer.llm.agent import LLMToolLoop

        tool_loop = LLMToolLoop(
            settings=resolved,
            registry=tool_registry,
            runtime=tool_runtime,
        )

    # Resolve agent registry: caller override wins, else build from
    # project_root (which falls back to the S0 sentinel; the loader
    # treats missing directories as "no project layer").
    resolved_agent_registry = (
        agent_registry
        if agent_registry is not None
        else built_agent_registry(project_root=root)
    )

    # Resolve story agent: caller override wins, else pick by genre.
    resolved_story_agent = (
        story_agent if story_agent is not None else _agent_for_genre(resolved, genre)
    )

    return _DefaultEngineDeps(
        router=_select_router(
            resolved,
            primary=primary_router,
            agent_registry=resolved_agent_registry,
        ),
        story_agent=resolved_story_agent,
        agent_registry=resolved_agent_registry,
        tool_registry=tool_registry,
        tool_runtime=tool_runtime,
        directive_registry=built_directive_registry(project_root=root),
        tool_loop=tool_loop,
        _workflows=dict(WORKFLOWS),
    )


__all__ = ["EngineDeps", "production_deps"]
