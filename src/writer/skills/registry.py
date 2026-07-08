"""Directive registry — lookup table for command-bound directives.

Renamed from ``SkillRegistry`` per chg-markdown-skills Decision 3.
The internal dict value type changed from ``Skill`` to ``SkillDirective``;
the public surface (``get`` / ``commands`` / ``help_entries`` /
``state_matrix``) is shape-compatible with the prior registry so
downstream callers (REPL help / tab completion / state-machine gating)
do not need to change their call sites — only the type names.

Discovery happens in three layers (Replace semantics — later wins on
command collision):

1. :func:`writer.skills.directive_discovery.discover_shipped_directives`
   — the 4 built-in directives in ``writer/skills/_shipped/``.
2. :func:`writer.skills.directive_discovery.discover_directives` — only
   when ``project_root`` is provided.
3. :func:`discover_entry_point_directives` — Python entry-point plugins
   under ``[project.entry-points."writer.directives"]``.

See :func:`built_directive_registry` for the composition.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from writer.skills.directive_discovery import (
    discover_entry_point_directives,
    discover_shipped_directives,
)
from writer.skills.errors import SkillError
from writer.skills.protocol import SkillDirective

if TYPE_CHECKING:
    from writer.project.state import ProjectState

log = logging.getLogger(__name__)


#: Entry-point group name for third-party directive plugins.
ENTRY_POINT_GROUP = "writer.directives"


def _validate(directive: SkillDirective) -> None:
    """Enforce the directive metadata contract at registration time.

    Catching problems early keeps a typo (``description = 123``) from
    surviving until the first ``/帮助`` call, where it would surface
    as a confusing render glitch.
    """

    if not isinstance(directive.command, str) or not directive.command.startswith("/"):
        msg = (
            f"Directive {directive!r} has invalid `command` "
            "(must be a non-empty str starting with '/')"
        )
        raise SkillError(msg)
    if not isinstance(directive.description, str) or not directive.description.strip():
        msg = f"Directive {directive.command!r} missing non-empty `description`"
        raise SkillError(msg)
    if (
        not isinstance(directive.requires_states, frozenset)
        or not directive.requires_states
    ):
        msg = (
            f"Directive {directive.command!r} has invalid `requires_states` "
            "(must be a non-empty frozenset[ProjectState])"
        )
        raise SkillError(msg)


class DirectiveRegistry:
    """Lookup table for command-bound directives.

    Duplicate commands are resolved with **last-write-wins** semantics:
    when the same ``command`` appears more than once across layers
    (shipped / project / entry-point), the later layer replaces the
    earlier one. This Replace semantics lets users override any shipped
    directive by adding a same-named project directive.

    Per-directive validation still raises :class:`SkillError` (via
    :func:`_validate`) — a malformed directive is always a hard error
    and will abort registry construction.
    """

    def __init__(
        self,
        directives: list[SkillDirective] | None = None,
        *,
        extra_directives: list[SkillDirective] | None = None,
    ) -> None:
        items: list[SkillDirective] = (
            list(directives) if directives is not None else []
        )
        if extra_directives:
            items.extend(extra_directives)

        seen: dict[str, SkillDirective] = {}
        for directive in items:
            _validate(directive)
            seen[directive.command] = directive

        self._by_command: dict[str, SkillDirective] = seen

    # ----- introspection ----------------------------------------------------

    def get(self, command: str) -> SkillDirective | None:
        return self._by_command.get(command)

    def commands(self) -> list[str]:
        """Return sorted slash commands (stable across runs)."""

        return sorted(self._by_command)

    def help_entries(self) -> list[tuple[str, str]]:
        """Return ``[(command, description), …]`` in registry order.

        Sorted by :meth:`commands` so ``/帮助`` rendering stays stable
        regardless of insertion order.
        """

        return [(cmd, self._by_command[cmd].description) for cmd in self.commands()]

    def state_matrix(self) -> dict[str, frozenset[ProjectState]]:
        """Return ``{command: requires_states}`` for every registered directive.

        Powers :func:`writer.project.validate_command_available` so the
        state matrix for directive-driven commands is fully derived from
        directive metadata — adding a directive updates its availability
        map automatically.
        """

        return {cmd: self._by_command[cmd].requires_states for cmd in self.commands()}

    # ----- execution --------------------------------------------------------

    def get_body_with_references(
        self, command: str
    ) -> tuple[str, list[tuple[str, str]]] | None:
        """Return ``(body, resolved_references)`` for ``command``.

        ``resolved_references`` is the list of ``(relpath, content)``
        pairs matched by ``@reference path`` mentions in the body, in
        the order they appear. Returns ``None`` if the command is not
        registered.

        Imported lazily to avoid a circular import between registry and
        directive_discovery at module load time.
        """

        directive = self.get(command)
        if directive is None:
            return None
        # Local import: directive_discovery imports from this module's
        # level, so we resolve references at call time to avoid the cycle.
        from writer.skills.directive_discovery import resolve_references  # noqa: PLC0415

        return directive.body, resolve_references(directive.body, directive.references)


__all__ = [
    "DirectiveRegistry",
    "ENTRY_POINT_GROUP",
    "built_directive_registry",
]


def built_directive_registry(
    project_root: Path | None = None,
) -> DirectiveRegistry:
    """Built-in directives + project-level directives + entry-point directives.

    Layers (Replace semantics — later wins on command collision):

    1. :func:`discover_shipped_directives` — the 4 shipped directives.
    2. :func:`discover_directives(project_root)` — only when
       ``project_root`` is provided.
    3. :func:`discover_entry_point_directives` — Python entry-point
       plugins.

    The ``project_root=None`` path preserves the legacy behavior (no
    project layer; back-compat for tests and callers that do not have
    a project bound).

    The function never raises for missing project skills (the loader
    swallows per-file errors as warnings) and never raises for missing
    entry-point plugins. A truly empty registry (no built-ins, no
    project, no plugins) is still valid.
    """

    items: list[SkillDirective] = list(discover_shipped_directives())

    if project_root is not None:
        from writer.skills.directive_discovery import discover_directives  # noqa: PLC0415

        items.extend(discover_directives(project_root))

    items.extend(discover_entry_point_directives())

    if len(items) == 0:
        # No built-ins AND no project AND no plugins. This should not
        # happen in production (the shipped layer always provides 4),
        # but we tolerate it for tests + bootstrap.
        return DirectiveRegistry()
    return DirectiveRegistry(directives=items)
