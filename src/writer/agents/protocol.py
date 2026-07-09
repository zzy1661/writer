"""Agent Protocol — pure Markdown frontmatter paradigm.

An agent is a self-contained instruction set stored as a single ``.md``
file (mirroring Claude Code's ``~/.claude/agents/`` layout). Each
agent has:

* ``name`` — stable identifier (``history`` / ``romance`` / ``xuanhuan``
  / ``other``). Used by :class:`AgentRegistry` as the dict key and by
  the parent LLM to ``target_agent=`` in :class:`AgentAction`.
* ``description`` — natural-language one-liner that the parent LLM
  reads to decide whether to dispatch to this agent. Required to be
  informative: should name 3+ concrete trigger scenarios.
* ``genre`` — canonical project genre key (``other`` / ``历史`` /
  ``言情`` / ``玄幻``). Used by the LLM call layer to look up the
  matching :class:`ChatPromptTemplate` for outline / TOC / init-brief
  flows; **not** used for dispatch (the LLM picks based on
  ``description``).
* ``body`` — full Markdown body of the ``.md`` file (frontmatter
  stripped, trailing whitespace normalized). Becomes the system
  identity for the agent's LLM call.
* ``tools_allowlist`` — optional tuple of tool names this agent is
  allowed to invoke. **Reserved for future use**; the engine does NOT
  enforce this list yet (per the ``fea-agent-mirror`` design decision
  to ship the field but defer enforcement to a later change).
* ``root`` — absolute path of the agent's file, for diagnostics and
  future safe-path integrations.

Discovery happens via :func:`writer.agents.agent_discovery.discover_agents`
(project-level) and :func:`...discover_shipped_agents` (package
internals under ``writer/agents/_shipped/``). Both feed into
:class:`writer.agents.registry.AgentRegistry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Agent:
    """A loaded ``<name>.md`` agent.

    See module docstring for the field contract.
    """

    name: str
    description: str
    genre: str
    body: str
    tools_allowlist: tuple[str, ...] = ()
    root: Path = field(default_factory=Path)


__all__ = ["Agent"]
