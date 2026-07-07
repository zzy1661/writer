"""Skill registry — maps slash commands to skill implementations.

The registry exposes four metadata surfaces so the rest of the system
does not need to know skill class internals:

* :meth:`get` — invoke by slash command (engine loop hot path).
* :meth:`commands` — sorted list of slash commands (REPL tab completion).
* :meth:`help_entries` — ``[(command, description), …]`` for
  ``/帮助`` rendering.
* :meth:`state_matrix` — ``{command: frozenset[ProjectState]}`` used by
  :func:`writer.project.validate_command_available` to detect
  unavailable commands.

Third-party plugins extend the registry by adding an ``[project
.entry-points."writer.skills"]`` section to their ``pyproject.toml``:

.. code-block:: toml

   [project.entry-points."writer.skills"]
   my_skill = "my_pkg.my_skill:MySkill"

``MySkill`` may be either a class (instantiated with no args) or a
pre-built instance. Discovery failures (ImportError, missing class,
bad signature) are logged at WARNING and skipped — they never block
startup, mirroring the design choice from
:func:`writer.tools.registry.built_tool_registry`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from importlib import metadata
from typing import TYPE_CHECKING

from writer.skills.continue_writing import ContinueWritingSkill
from writer.skills.errors import SkillError
from writer.skills.outline import OutlineSkill
from writer.skills.protocol import Skill
from writer.skills.revise import ReviseSkill
from writer.skills.toc import TocSkill

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps
    from writer.engine.events import Done, TextChunk
    from writer.project.state import ProjectState

log = logging.getLogger(__name__)


ENTRY_POINT_GROUP = "writer.skills"


# Built-in skills shipped with the agent. Order matters only for the
# fall-through default-arg case in :class:`SkillRegistry` (later
# registrations win on command collision, which mirrors entry-point
# overrides being last). The defaults here stay synchronous and
# instance-class based so test fixtures can reconstruct the same
# registry without poking at module globals.
BUILTIN_SKILLS: list[Skill] = [
    OutlineSkill(),
    TocSkill(),
    ContinueWritingSkill(),
    ReviseSkill(),
]


def _validate_skill(skill: Skill) -> None:
    """Enforce the Skill metadata contract at registration time.

    Catching problems early keeps a typo (``description = 123``) from
    surviving until the first ``/帮助`` call, where it would surface as a
    confusing render glitch.
    """

    command = getattr(skill, "command", None)
    description = getattr(skill, "description", None)
    requires_states = getattr(skill, "requires_states", None)

    if not isinstance(command, str) or not command.startswith("/"):
        msg = (
            f"Skill {skill!r} missing a valid `command` "
            "(must be a non-empty str starting with '/')"
        )
        raise SkillError(msg)
    if not isinstance(description, str) or not description.strip():
        msg = f"Skill {command!r} missing a non-empty `description`"
        raise SkillError(msg)
    if not isinstance(requires_states, frozenset) or not requires_states:
        msg = (
            f"Skill {command!r} has invalid `requires_states` "
            "(must be a non-empty frozenset[ProjectState])"
        )
        raise SkillError(msg)


class SkillRegistry:
    """Lookup table for command-bound skills.

    Duplicate commands raise :class:`SkillError` at construction time —
    earlier (built-in) entries win, so passing the same command twice
    is a configuration error rather than silent last-write-wins.
    """

    def __init__(
        self,
        skills: list[Skill] | None = None,
        *,
        extra_skills: list[Skill] | None = None,
    ) -> None:
        items: list[Skill] = list(skills) if skills is not None else list(BUILTIN_SKILLS)
        if extra_skills:
            items.extend(extra_skills)

        seen: dict[str, Skill] = {}
        for skill in items:
            _validate_skill(skill)
            if skill.command in seen:
                msg = (
                    f"duplicate skill command {skill.command!r}: "
                    f"{seen[skill.command].__class__.__name__} vs {skill.__class__.__name__}"
                )
                raise SkillError(msg)
            seen[skill.command] = skill

        self._by_command: dict[str, Skill] = seen

    # ----- introspection ----------------------------------------------------

    def get(self, command: str) -> Skill | None:
        return self._by_command.get(command)

    def commands(self) -> list[str]:
        """Return sorted slash commands.

        Sort order is stable across runs (alphabetical on bytes), which
        keeps REPL tab completion deterministic across machines.
        """

        return sorted(self._by_command)

    def help_entries(self) -> list[tuple[str, str]]:
        """Return ``[(command, description), …]`` in registry order.

        Sorted by ``commands()`` so ``/帮助`` rendering stays stable
        regardless of insertion order. Used by
        :func:`writer.cli.main.print_repl_help`.
        """

        return [(cmd, self._by_command[cmd].description) for cmd in self.commands()]

    def state_matrix(self) -> dict[str, frozenset[ProjectState]]:
        """Return ``{command: requires_states}`` for every registered skill.

        Powers :func:`writer.project.validate_command_available` so the
        state matrix for skill-driven commands is fully derived from
        skill metadata — adding a skill updates its availability map
        automatically.
        """

        return {cmd: self._by_command[cmd].requires_states for cmd in self.commands()}

    # ----- execution --------------------------------------------------------

    def run(
        self,
        command: str,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        skill = self.get(command)
        if skill is None:
            msg = f"未注册 skill: {command}"
            raise SkillError(msg)
        return skill.run(ctx, deps, cfg)


def discover_entry_point_skills() -> list[Skill]:
    """Discover skills registered as ``[project.entry-points."writer.skills"]``.

    Each entry point may resolve to either:

    * a ``Skill`` class — instantiated with no arguments;
    * a pre-built ``Skill`` instance — used as-is.

    Anything that fails to resolve (missing distribution, ImportError,
    bad attribute, unexpected type, ``SkillError`` from validators) is
    logged at WARNING and skipped so a broken plugin never blocks the
    REPL from starting.
    """

    discovered: list[Skill] = []
    try:
        entries = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # noqa: BLE001 — entry-points API can raise in odd envs
        log.warning("Skill entry_points discovery failed; continuing without plugins")
        return discovered

    for entry in entries:
        try:
            target = entry.load()
        except Exception:  # noqa: BLE001 — misbehaving plugins must not crash startup
            log.warning(
                "Failed to import skill entry point %s=%s; skipping",
                entry.name,
                entry.value,
            )
            continue

        try:
            if isinstance(target, type):
                instance: Skill = target()  # type: ignore[abstract]
            elif isinstance(target, Skill):
                instance = target
            else:
                log.warning(
                    "Skill entry point %s did not resolve to a Skill "
                    "(got %s); skipping",
                    entry.name,
                    type(target).__name__,
                )
                continue
        except Exception:  # noqa: BLE001 — constructor failures must not crash startup
            log.warning(
                "Skill entry point %s constructor raised; skipping",
                entry.name,
            )
            continue

        try:
            _validate_skill(instance)
        except SkillError as exc:
            log.warning("Skill entry point %s rejected: %s", entry.name, exc)
            continue

        discovered.append(instance)
    return discovered


def built_skill_registry() -> SkillRegistry:
    """Built-in skills + entry-point skills; built-ins win on command collision.

    Built-ins come first so a plugin shadowing ``/大纲`` triggers the
    duplicate-command error in :class:`SkillRegistry.__init__` — this
    is intentional: silently letting a plugin clobber a core skill
    would make behaviour non-deterministic and hard to debug.
    """

    extras = discover_entry_point_skills()
    if not extras:
        return SkillRegistry()
    return SkillRegistry(skills=list(BUILTIN_SKILLS), extra_skills=extras)


__all__ = [
    "BUILTIN_SKILLS",
    "ENTRY_POINT_GROUP",
    "SkillRegistry",
    "built_skill_registry",
    "discover_entry_point_skills",
]
