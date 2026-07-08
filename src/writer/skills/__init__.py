"""Directive system — pure Markdown SKILL.md paradigm.

Every directive is a directory under ``<project_root>/.writer/skills/``
(or ``src/writer/skills/_shipped/`` for built-ins) containing a
``SKILL.md`` file plus optional ``references/`` and ``scripts/``
subdirectories. Discovery happens via the ``directive_discovery``
helpers; the engine reads the directive's body and ``@reference``'d
files into the LLM context.

Public surface (per chg-markdown-skills):

* :class:`SkillDirective` — frozen dataclass loaded from ``SKILL.md``.
* :class:`DirectiveRegistry` — lookup table keyed by ``command``.
* :func:`built_directive_registry` — factory assembling shipped +
  project + entry-point layers (later wins on command collision).
* :func:`discover_directives` — scan a project's skills directory.
* :func:`discover_shipped_directives` — list the 4 shipped directives.
* :func:`discover_entry_point_directives` — entry-point plugin hook.
* :class:`SkillError` — domain exception (re-exported for back-compat).
"""

from writer.skills.directive_discovery import (
    discover_directives,
    discover_shipped_directives,
    resolve_references,
)
from writer.skills.errors import SkillError
from writer.skills.protocol import SkillDirective
from writer.skills.registry import (
    DirectiveRegistry,
    ENTRY_POINT_GROUP,
    built_directive_registry,
    discover_entry_point_directives,
)

__all__ = [
    "DirectiveRegistry",
    "ENTRY_POINT_GROUP",
    "SkillDirective",
    "SkillError",
    "built_directive_registry",
    "discover_directives",
    "discover_entry_point_directives",
    "discover_shipped_directives",
    "resolve_references",
]