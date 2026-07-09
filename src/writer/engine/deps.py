"""Dependency injection boundary for the agent engine.

The engine never instantiates its collaborators directly — every external
boundary is declared here as a ``Protocol``. This matches Claude Code §十
"最小接口 DI": we only inject what gets swapped (tests, alternate routers,
future LLM-backed implementations).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from writer.agents import AgentRegistry, built_agent_registry
from writer.config import Settings, get_settings
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
from writer.workflows import WORKFLOWS, WorkflowResult, WorkflowStub

if TYPE_CHECKING:
    from writer.engine.context import EngineContext
    from writer.llm.agent import LLMToolLoop
    from writer.llm.prose import LLMProseClient

# Sentinel project_root used when no project is initialized (S0 path).
# Tools that need file access will fail their safe_path check; tools that
# don't (foreshadow_search, chapter_locate, wordcount) still work.
_NO_PROJECT_ROOT = Path("/__no_project__")


@runtime_checkable
class EngineDeps(Protocol):
    """Minimum surface the engine loop depends on.

    Current fields:

    * :attr:`router` — front-desk dispatcher (per 备忘 15; Protocol
      :class:`writer.routing.IntentRouter`).
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

    ``story_agent`` was removed in ``chg-remove-roles`` (2026-07-09):
    the four ``*Agent`` Python classes became dead code once
    ``fea-agent-mirror`` moved LLM-facing identity to Markdown; the
    only surviving Python-side capability (``process_init_brief``)
    reads ``Settings`` directly and does not need a per-role instance.

    Future expansion points (intentionally not declared yet):
    * ``workflow_starter``: richer async workflow entrypoint
      (per 备忘 04; the current sync ``run_workflow`` is the MVP bridge)
    * ``interrupt_handler``: InterruptHandler (per 备忘 14)
    * ``stop_hooks``: StopHookRegistry (Claude Code §十二·12.3)
    """

    router: IntentRouter
    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    directive_registry: DirectiveRegistry
    tool_loop: LLMToolLoop | None
    prose_client: LLMProseClient | None
    # Optional override for the review LLM. When set, ``write_chapter``
    # uses this LLM for the structured ReviewVerdict call instead of
    # constructing a fresh ``ChatOpenAI`` from settings. Tests inject
    # recording fakes here; production leaves it None.
    review_llm: Any

    def route(self, user_input: str, project_state: str) -> AgentAction:
        ...

    def run_workflow(self, name: str, ctx: EngineContext) -> WorkflowResult:
        ...

    def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the runtime swapped.
        Called by :meth:`writer.session.EngineSession.set_project_root` to
        point the existing deps at a new project root without rebuilding
        router / tool_registry. Implementations are
        free to return a new instance (default impl uses ``dataclasses
        .replace``) or mutate ``self`` — both are valid as long as the
        returned value is used as the new deps.

        Added 2026-07-05 to fix arch-optimizer M6: the old code
        duck-typed ``is_dataclass(self.deps) and any(f.name == ...)``,
        which broke the moment a test injected a non-dataclass
        ``EngineDeps`` implementation.
        """
        ...

    def rebind_skill_registry(
        self, new_registry: DirectiveRegistry
    ) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the directive registry swapped.

        Symmetric to :meth:`rebind_tool_runtime`. Called by
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

        Symmetric to :meth:`rebind_tool_runtime`. Called by
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
    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    directive_registry: DirectiveRegistry
    tool_loop: LLMToolLoop | None = None
    prose_client: LLMProseClient | None = None
    review_llm: Any = None
    _workflows: dict[str, WorkflowStub] = field(default_factory=dict)

    def route(self, user_input: str, project_state: str) -> AgentAction:
        return self.router.route(user_input, project_state)

    def run_workflow(self, name: str, ctx: EngineContext) -> WorkflowResult:
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
        # The default wiring dispatches to the package-level
        # :func:`writer.workflows.run_workflow` adapter, which inspects
        # the registered callable's signature and passes ``deps`` (this
        # instance) for PR2+ workflows. The adapter also wraps any
        # legacy ``Iterable[str]`` returns into :class:`WorkflowResult`.
        from writer.workflows import run_workflow as _run_workflow_dispatch

        return _run_workflow_dispatch(name, ctx, self)

    def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> EngineDeps:
        # Use ``dataclasses.replace`` so the production wiring stays
        # effectively immutable; tests that need mutation can still
        # override the method.
        return replace(self, tool_runtime=new_runtime)

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
        # Symmetric to ``rebind_tool_runtime``; uses ``dataclasses.replace``
        # to keep the production wiring effectively immutable. Per chg-markdown-skills:
        # project-level directives live in the project directory, so this MUST be
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
) -> EngineDeps:
    """Default dependency wiring used by the REPL and tests.

    Pure factory: no filesystem IO behind the caller's back.

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

    Removed in ``chg-remove-roles`` (2026-07-09):
        * ``story_agent=`` kwarg — ``writer.roles.StoryAgent`` and its
          three subclasses are gone; ``EngineDeps.story_agent`` was
          the only consumer.
        * ``genre=`` kwarg — was used by the deleted
          ``_agent_for_genre`` factory; the only surviving consumer
          (``EngineSession.refresh_project_genre``) reads ``AGENT.md``
          itself before the session constructs deps.
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

    # Resolve the prose client. Always populated (never None): the
    # Real variant is wired when the API key is configured, otherwise
    # the Deterministic variant. ``production_deps`` is the only place
    # that decides which one to use — engine / workflow code branches
    # on ``deps.prose_client.name`` (``"real"`` vs ``"deterministic"``)
    # rather than on API-key presence. Per real-writing-pipeline PR2.
    from writer.llm.prose import (
        DeterministicProseClient,
        RealProseClient,
    )

    if resolved.has_api_key:
        from writer.llm.provider import get_llm as _get_llm

        prose_client: LLMProseClient = RealProseClient(llm=_get_llm(resolved))
    else:
        prose_client = DeterministicProseClient()

    # Resolve agent registry: caller override wins, else build from
    # project_root (which falls back to the S0 sentinel; the loader
    # treats missing directories as "no project layer").
    resolved_agent_registry = (
        agent_registry
        if agent_registry is not None
        else built_agent_registry(project_root=root)
    )

    return _DefaultEngineDeps(
        router=_select_router(
            resolved,
            primary=primary_router,
            agent_registry=resolved_agent_registry,
        ),
        agent_registry=resolved_agent_registry,
        tool_registry=tool_registry,
        tool_runtime=tool_runtime,
        directive_registry=built_directive_registry(project_root=root),
        tool_loop=tool_loop,
        prose_client=prose_client,
        _workflows=dict(WORKFLOWS),
    )


__all__ = ["EngineDeps", "production_deps"]
