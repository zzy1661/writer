"""Skill registry — maps slash commands to skill implementations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from writer.engine.config import EngineConfig
from writer.engine.context import EngineContext
from writer.engine.events import Done, TextChunk
from writer.skills.outline import OutlineSkill
from writer.skills.protocol import Skill
from writer.skills.toc import TocSkill

if TYPE_CHECKING:
    from writer.engine.deps import EngineDeps


class SkillRegistry:
    """Lookup table for command-bound skills."""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        items: list[Skill] = skills if skills is not None else [OutlineSkill(), TocSkill()]
        self._by_command: dict[str, Skill] = {skill.command: skill for skill in items}

    def get(self, command: str) -> Skill | None:
        return self._by_command.get(command)

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
            raise KeyError(msg)
        return skill.run(ctx, deps, cfg)


def built_skill_registry() -> SkillRegistry:
    return SkillRegistry()


__all__ = ["SkillRegistry", "built_skill_registry"]
