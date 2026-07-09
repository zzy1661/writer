"""Agent registry — lookup table for name-bound agents.

Last-write-wins semantics: when the same ``name`` appears more than
once across layers (shipped / project / entry-point), the later layer
replaces the earlier one. This Replace semantics lets users override
any shipped agent by adding a same-named project agent.

Duplicate names within a single layer raise :class:`AgentRegistryError`
at registry construction time. A malformed agent is also rejected
up-front (see :func:`_validate`) so a typo (``description = 123``)
cannot survive until the first LLM dispatch.

Public surface:

* :class:`AgentRegistry` — lookup table keyed by ``name``.
* :func:`built_agent_registry` — factory assembling shipped + project
  + entry-point layers (later wins on name collision).
* :func:`builtin_agent_registry` — built-in agents only.

The :meth:`AgentRegistry.descriptions` view powers the parent LLM's
dispatch decision (per :class:`writer.routing.LlmIntentRouter`):

* Each description is truncated to ≤ 200 characters.
* The total list is capped at 16 agents (a soft warning, not an error)
  so the router's system prompt never explodes.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.agents.protocol import Agent

log = logging.getLogger(__name__)


#: Entry-point group name for third-party agent plugins.
ENTRY_POINT_GROUP = "writer.agents"


#: Maximum characters per description in :meth:`AgentRegistry.descriptions`.
DESCRIPTION_MAX_CHARS = 200

#: Maximum number of agents returned by :meth:`AgentRegistry.descriptions`.
DESCRIPTIONS_MAX_AGENTS = 16

#: Allow-list of canonical genre keys (per ``fea-agent-mirror`` Decision 7).
_VALID_GENRES: frozenset[str] = frozenset({"other", "历史", "言情", "玄幻"})

#: Pattern for the ``name`` field — lowercase, starts with a letter,
#: then letters / digits / underscore.
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class AgentRegistryError(ValueError):
    """Raised when an agent registration is invalid (bad name, duplicate, schema)."""


def _validate(agent: object) -> None:
    """Enforce the agent metadata contract at registration time.

    Catching problems early keeps a typo (``description = 123``) from
    surviving until the first LLM dispatch, where it would surface
    as a confusing render glitch.
    """

    # Lazy import to avoid top-level circulars (this module is imported
    # by writer.agents.__init__ which may be loaded before the protocol
    # is fully resolved during package init).
    from writer.agents.protocol import Agent

    if not isinstance(agent, Agent):
        msg = f"agent must be an Agent instance; got {type(agent).__name__}"
        raise AgentRegistryError(msg)

    if not isinstance(agent.name, str) or not _NAME_PATTERN.match(agent.name):
        msg = (
            f"Agent {agent!r} has invalid `name` {agent.name!r} "
            "(must match ^[a-z][a-z0-9_]*$)"
        )
        raise AgentRegistryError(msg)
    if not isinstance(agent.description, str) or not agent.description.strip():
        msg = f"Agent {agent.name!r} missing non-empty `description`"
        raise AgentRegistryError(msg)
    if not isinstance(agent.genre, str) or agent.genre not in _VALID_GENRES:
        msg = (
            f"Agent {agent.name!r} has invalid `genre` {agent.genre!r}; "
            f"expected one of {sorted(_VALID_GENRES)}"
        )
        raise AgentRegistryError(msg)
    if not isinstance(agent.body, str) or not agent.body.strip():
        msg = f"Agent {agent.name!r} missing non-empty `body`"
        raise AgentRegistryError(msg)


class AgentRegistry:
    """Lookup table for name-bound agents.

    Duplicate names are resolved with **last-write-wins** semantics:
    when the same ``name`` appears more than once across layers
    (shipped / project / entry-point), the later layer replaces the
    earlier one. This Replace semantics lets users override any
    shipped agent by adding a same-named project agent.

    Per-agent validation raises :class:`AgentRegistryError` (via
    :func:`_validate`) — a malformed agent is always a hard error and
    will abort registry construction.
    """

    def __init__(
        self,
        agents: list[Agent] | None = None,
        *,
        extra_agents: list[Agent] | None = None,
    ) -> None:
        items: list[Agent] = list(agents) if agents is not None else []
        if extra_agents:
            items.extend(extra_agents)

        seen: dict[str, Agent] = {}
        for agent in items:
            _validate(agent)
            seen[agent.name] = agent  # last-write-wins

        self._by_name: dict[str, Agent] = seen

    # ----- introspection --------------------------------------------------

    def get(self, name: str) -> Agent | None:
        return self._by_name.get(name)

    def require(self, name: str) -> Agent:
        """Return the agent for ``name`` or raise :class:`AgentRegistryError`.

        Mirrors :meth:`writer.skills.registry.DirectiveRegistry.run`-style
        strictness: missing names surface as a clear error rather than
        ``None`` so the engine's ``Done(aborted)`` payload is informative.
        """

        agent = self._by_name.get(name)
        if agent is None:
            available = sorted(self._by_name)
            msg = f"no agent registered for name {name!r}; available: {available}"
            raise AgentRegistryError(msg)
        return agent

    def all(self) -> list[Agent]:
        """Return all registered agents, sorted by name."""

        return [self._by_name[name] for name in sorted(self._by_name)]

    def names(self) -> list[str]:
        """Return sorted agent names (stable across runs)."""

        return sorted(self._by_name)

    def descriptions(self) -> list[dict[str, str]]:
        """Return ``[{name, description, genre}, …]`` for LLM dispatch.

        Each description is truncated to :data:`DESCRIPTION_MAX_CHARS`;
        the total list is capped at :data:`DESCRIPTIONS_MAX_AGENTS`
        (with a WARNING log on truncation). The original ``Agent``
        objects are NOT mutated — this is a read view.
        """

        out: list[dict[str, str]] = []
        truncated_total = False
        for name in self.names():
            if len(out) >= DESCRIPTIONS_MAX_AGENTS:
                truncated_total = True
                break
            agent = self._by_name[name]
            description = agent.description
            if len(description) > DESCRIPTION_MAX_CHARS:
                description = description[:DESCRIPTION_MAX_CHARS]
            out.append(
                {
                    "name": name,
                    "description": description,
                    "genre": agent.genre,
                }
            )

        if truncated_total:
            log.warning(
                "AgentRegistry.descriptions() truncated from %d to %d "
                "agents to keep the LLM system prompt bounded",
                len(self._by_name),
                DESCRIPTIONS_MAX_AGENTS,
            )
        return out


__all__ = [
    "AgentRegistry",
    "AgentRegistryError",
    "DESCRIPTION_MAX_CHARS",
    "DESCRIPTIONS_MAX_AGENTS",
    "ENTRY_POINT_GROUP",
    "built_agent_registry",
    "builtin_agent_registry",
]


def builtin_agent_registry() -> AgentRegistry:
    """Built-in agents only — no project layer, no entry-point plugins.

    Used as the default by callers that don't have a project bound
    (e.g. tests, ``S0`` path).
    """

    from writer.agents.agent_discovery import discover_shipped_agents  # noqa: PLC0415

    items: list[Agent] = list(discover_shipped_agents())  # type: ignore[arg-type]
    return AgentRegistry(agents=items)


def built_agent_registry(
    project_root: Path | None = None,
) -> AgentRegistry:
    """Built-in agents + project-level agents + entry-point plugins.

    Layers (Replace semantics — later wins on name collision):

    1. :func:`discover_shipped_agents` — the 4 shipped agents.
    2. :func:`discover_agents(project_root)` — only when
       ``project_root`` is provided.
    3. :func:`discover_entry_point_agents` — Python entry-point
       plugins.

    The ``project_root=None`` path preserves the legacy behaviour (no
    project layer; back-compat for tests and callers that do not have
    a project bound). The function never raises for missing project
    files (the loader swallows per-file errors as warnings) and never
    raises for missing entry-point plugins. A truly empty registry
    (no built-ins, no project, no plugins) is still valid.
    """

    from writer.agents.agent_discovery import (  # noqa: PLC0415
        discover_agents,
        discover_entry_point_agents,
        discover_shipped_agents,
    )

    items: list[Agent] = []
    items.extend(discover_shipped_agents())  # type: ignore[arg-type]
    if project_root is not None:
        items.extend(discover_agents(project_root))  # type: ignore[arg-type]
    items.extend(discover_entry_point_agents())  # type: ignore[arg-type]

    _check_builtin_sources_drift()

    if len(items) == 0:
        return AgentRegistry()
    return AgentRegistry(agents=items)


def _check_builtin_sources_drift() -> None:
    """Log a WARNING if any shipped agent file's sha256 no longer matches.

    Soft check — the registry still loads the file (drift is a
    maintenance signal, not a hard failure). See
    :class:`writer.agents.builtin_sources.BUILTIN_AGENT_SOURCES`.
    """

    try:
        from writer.agents.builtin_sources import BUILTIN_AGENT_SOURCES  # noqa: PLC0415
    except ImportError:
        return

    import hashlib
    import importlib.resources

    try:
        shipped_root = importlib.resources.files("writer.agents._shipped")
    except Exception:  # noqa: BLE001
        return

    for entry in BUILTIN_AGENT_SOURCES:
        try:
            traversable = shipped_root / entry.mirror_filename
            text = traversable.read_text(encoding="utf-8")
        except (OSError, NotImplementedError):
            continue
        actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual_sha != entry.source_sha256:
            log.warning(
                "Shipped agent %s drifted: expected sha=%s, actual sha=%s; "
                "registry will still load the drifted file but you may want "
                "to refresh BUILTIN_AGENT_SOURCES",
                entry.mirror_filename,
                entry.source_sha256,
                actual_sha,
            )
