"""Skill implementations.

Skills are composable, reusable behaviors invoked by the engine for
specific slash commands (``/大纲``, ``/目录``, ``/续写``, ``/改``, …).

Each skill declares four pieces of metadata on its class —
``command``, ``description``, ``requires_states``, ``extra_instructions``
— and an async ``run()`` method that the engine loop dispatches to. The
:class:`writer.skills.registry.SkillRegistry` validates the metadata
at construction time and exposes ``help_entries`` / ``state_matrix``
/ ``commands`` so the CLI help text and the state machine can be
derived without touching skill code.

Skill discovery happens in three layers (Replace semantics — later
wins):

1. :data:`writer.skills.registry.BUILTIN_SKILLS` — the four shipped
   skills, hardcoded in the package.
2. :func:`writer.skills.loader.discover_project_skills` — project-level
   overrides at ``<project_root>/.writer/skills/``; replaces built-ins
   by command when present.
3. :func:`writer.skills.registry.discover_entry_point_skills` — Python
   entry points registered as ``writer.skills`` plugins; replaces both
   built-ins and project skills by command when present.
"""

from writer.skills.builtin_sources import (
    BUILTIN_SKILL_SOURCES,
    MIRROR_HEADER_TEMPLATE,
    BuiltinSkillSource,
    mirror_filename_for,
)
from writer.skills.continue_writing import ContinueWritingSkill
from writer.skills.errors import SkillError
from writer.skills.loader import discover_project_skills
from writer.skills.outline import OutlineSkill
from writer.skills.protocol import Skill
from writer.skills.registry import (
    BUILTIN_SKILLS,
    ENTRY_POINT_GROUP,
    SkillRegistry,
    built_skill_registry,
    discover_entry_point_skills,
)
from writer.skills.revise import ReviseSkill
from writer.skills.toc import TocSkill

__all__ = [
    "BUILTIN_SKILLS",
    "BUILTIN_SKILL_SOURCES",
    "BuiltinSkillSource",
    "ContinueWritingSkill",
    "ENTRY_POINT_GROUP",
    "MIRROR_HEADER_TEMPLATE",
    "OutlineSkill",
    "ReviseSkill",
    "Skill",
    "SkillError",
    "SkillRegistry",
    "TocSkill",
    "built_skill_registry",
    "discover_entry_point_skills",
    "discover_project_skills",
    "mirror_filename_for",
]
