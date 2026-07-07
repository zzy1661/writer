"""Skill protocol — composable command handlers for the engine.

A ``Skill`` is a self-contained command handler that the engine loop
dispatches to for a single ``/slash-command``. Skills are the engine's
extension point: third-party plugins register new skills via
``[project.entry-points."writer.skills"]`` in their ``pyproject.toml``
(per :func:`writer.skills.registry.discover_entry_point_skills`).

Metadata contract (``command`` / ``description`` / ``requires_states``)
drives three downstream surfaces:

* ``/帮助`` — :meth:`writer.cli.main.print_repl_help` uses
  :meth:`writer.skills.registry.SkillRegistry.help_entries` to render the
  command table without touching any skill code.
* REPL 补全 — :func:`writer.cli.main.build_prompt_session` uses
  :meth:`writer.skills.registry.SkillRegistry.commands` for tab completion.
* 状态机拦截 — :func:`writer.project.validate_command_available` consults
  :meth:`writer.skills.registry.SkillRegistry.state_matrix` so adding a new
  skill automatically wires its availability map (no need to touch
  ``COMMAND_ALLOWED``).

``requires_states`` is a ``frozenset`` so the Protocol field is hashable
and reusable as a registry key.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps
    from writer.engine.events import Done, TextChunk
    from writer.project.state import ProjectState


@runtime_checkable
class Skill(Protocol):
    """A reusable command handler invoked by the engine loop.

    Implementations must provide three class/instance attributes:

    * ``command: str`` — slash command, e.g. ``"/大纲"``.
    * ``description: str`` — short user-facing help text, e.g.
      ``"生成或查看大纲"``.
    * ``requires_states: frozenset[ProjectState]`` — lifecycle states
      where this skill is meaningful. The state matrix uses this to
      reject commands issued in incompatible states (e.g. ``/续写``
      requires ``WRITING``).
    """

    command: str
    description: str
    requires_states: frozenset[ProjectState]

    def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        ...


__all__ = ["Skill"]
