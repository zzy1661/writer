"""Skill implementations.

Skills are composable, reusable behaviors invoked by the engine for
specific slash commands (``/大纲``, ``/目录``, ``/续写``, ``/改``, …).

Each skill declares three pieces of metadata on its class —
``command``, ``description``, ``requires_states`` — and an async
``run()`` method that the engine loop dispatches to. The
:class:`writer.skills.registry.SkillRegistry` validates the metadata
at construction time and exposes ``help_entries`` / ``state_matrix``
/ ``commands`` so the CLI help text and the state machine can be
derived without touching skill code.
"""

from writer.skills.continue_writing import ContinueWritingSkill
from writer.skills.errors import SkillError
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
    "ContinueWritingSkill",
    "ENTRY_POINT_GROUP",
    "OutlineSkill",
    "ReviseSkill",
    "Skill",
    "SkillError",
    "SkillRegistry",
    "TocSkill",
    "built_skill_registry",
    "discover_entry_point_skills",
]
