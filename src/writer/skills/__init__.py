"""Skill implementations.

Skills are composable, reusable behaviors invoked by the engine for
specific slash commands (``/大纲``, ``/目录``, …).
"""

from writer.skills.outline import OutlineSkill
from writer.skills.protocol import Skill
from writer.skills.registry import SkillRegistry, built_skill_registry
from writer.skills.toc import TocSkill

__all__ = [
    "OutlineSkill",
    "Skill",
    "SkillRegistry",
    "TocSkill",
    "built_skill_registry",
]
