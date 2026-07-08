"""Directive Protocol — pure Markdown SKILL.md paradigm.

A directive is a self-contained instruction set stored under
``<command>/SKILL.md`` (mirroring Claude Code's ``~/.claude/skills/``
layout). The engine reads the directive's body and `@reference`'d
content into the LLM context, and the LLM uses the existing tool
registry to do the actual work — there is no Python ``run()`` method.

Discovery happens via :func:`writer.skills.directive_discovery.discover_directives`
(project-level) and :func:`...discover_shipped_directives` (package
internals under ``writer/skills/_shipped/``). Both feed into
:class:`writer.skills.registry.DirectiveRegistry`.

Metadata contract (``command`` / ``description`` / ``requires_states`` /
``body`` / ``references`` / ``scripts`` / ``root``) drives four downstream
surfaces:

* ``/帮助`` — :func:`writer.cli.main.print_repl_help` uses
  :meth:`writer.skills.registry.DirectiveRegistry.help_entries` to render
  the command table without touching SKILL.md parsing.
* REPL 补全 — :func:`writer.cli.main.build_prompt_session` uses
  :meth:`DirectiveRegistry.commands` for tab completion.
* 状态机拦截 — :func:`writer.project.validate_command_available`
  consults :meth:`DirectiveRegistry.state_matrix` so adding a new
  directive automatically wires its availability map.
* Engine dispatch — :func:`writer.engine.loop.run_engine` recognises
  matched ``command`` and routes the directive's body + references into
  the LLM via the existing tool loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.project.state import ProjectState


@dataclass(frozen=True)
class SkillDirective:
    """A loaded ``<command>/SKILL.md`` directive.

    Fields:

    * ``command`` — slash command (from YAML frontmatter).
    * ``description`` — human-readable one-liner (from YAML frontmatter).
    * ``requires_states`` — lifecycle gate (from YAML frontmatter,
      parsed as a list of valid ``ProjectState`` names).
    * ``body`` — full Markdown body of ``SKILL.md`` (frontmatter stripped,
      trailing whitespace normalized).
    * ``references`` — ``{relpath: content}`` for every ``*.md`` under
      ``<command>/references/``. Absent directory → ``{}``.
    * ``scripts`` — relative paths of files under
      ``<command>/scripts/``. Absent directory → ``[]``.
    * ``root`` — absolute path of the directive's directory, so the
      engine can resolve script execution paths through ``safe_path``.
    """

    command: str
    description: str
    requires_states: frozenset[ProjectState]
    body: str
    references: dict[str, str] = field(default_factory=dict)
    scripts: list[str] = field(default_factory=list)
    root: Path = field(default_factory=Path)


__all__ = ["SkillDirective"]
