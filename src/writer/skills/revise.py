"""``/改`` skill — placeholder for the chapter revision flow.

Same role as :class:`writer.skills.continue_writing.ContinueWritingSkill`:
exists to validate the skill metadata pipeline (see that module's
docstring for the design rationale).

Future behaviour will read the chapter draft, take a natural-language
edit instruction from the user, and either rewrite in place or produce
a side-by-side diff via ``deps.story_consultant.revise_chapter(...)``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from writer.project import ProjectState

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps
    from writer.engine.events import Done, TextChunk


class ReviseSkill:
    command = "/改"
    description = "修改章节内容"
    requires_states = frozenset({ProjectState.WRITING})

    async def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        # Lazy import: see comment in ContinueWritingSkill.run().
        from writer.engine.events import Done, TextChunk

        del deps
        del ctx
        if not cfg.fast_mode:
            yield TextChunk(text="[engine] /改 → revise skill\n")
        yield TextChunk(text="[提示] /改 尚未实现，等待 LLM 接入。\n")
        yield Done(
            reason="command_pending",
            payload={"command": self.command, "todo": "revise_chapter"},
        )


__all__ = ["ReviseSkill"]
