"""Agent system — Claude Code ``.claude/agents/`` mirror.

Each agent is a single ``.md`` file with YAML frontmatter
(``name`` / ``description`` / ``genre``) plus a Markdown body that
becomes the agent's system prompt at LLM call time. The parent LLM
reads each agent's ``description`` to decide whether to dispatch to
it (via ``AgentAction.target_agent``).

Public surface (per ``fea-agent-mirror``):

* :class:`Agent` — frozen dataclass loaded from ``<name>.md``.
* :class:`AgentRegistry` — lookup table keyed by ``name`` (last-write-wins).
* :func:`built_agent_registry` — factory assembling shipped + project
  + entry-point layers (later wins on name collision).
* :func:`builtin_agent_registry` — built-in agents only.
* :func:`discover_agents` — scan a project's ``.writer/agents/`` directory.
* :func:`discover_shipped_agents` — list the 4 shipped agents.
* :func:`discover_entry_point_agents` — entry-point plugin hook.
* :class:`AgentRegistryError` — domain exception.
* :func:`parse_agent_file` — parse one ``.md`` file (used by tests).

Capability layer (per ``chg-remove-roles``):

* :class:`InitBriefResult` — structured output for the post-init brief.
* :func:`process_init_brief` — the only Python-side helper kept after
  the ``roles`` package deletion. Used by both the engine's
  ``_run_init_brief_command`` and the CLI's ``_maybe_apply_init_brief``
  paths.
"""

from writer.agents.agent_discovery import (
    discover_agents,
    discover_entry_point_agents,
    discover_shipped_agents,
    parse_agent_file,
)
from writer.agents.capability import InitBriefResult, process_init_brief
from writer.agents.protocol import Agent
from writer.agents.registry import (
    AgentRegistry,
    AgentRegistryError,
    built_agent_registry,
    builtin_agent_registry,
)

__all__ = [
    "Agent",
    "AgentRegistry",
    "AgentRegistryError",
    "InitBriefResult",
    "built_agent_registry",
    "builtin_agent_registry",
    "discover_agents",
    "discover_entry_point_agents",
    "discover_shipped_agents",
    "parse_agent_file",
    "process_init_brief",
]
