"""``/续写`` skill — placeholder for the continuation writer.

This is the implementation stub registered in
:func:`writer.skills.registry.built_skill_registry`. It exists to prove
the skill metadata pipeline (command / description / requires_states)
works end-to-end before the real LLM-backed continuation logic lands.

When the LLM path is wired in, this skill will:

* read the latest chapter draft (or partial draft) under ``manuscript/``
* ask ``deps.story_consultant.continue_chapter(...)`` for the next
  chunk
* append the chunk to the current draft and yield a streaming
  ``TextChunk`` per paragraph
* close with ``Done(reason='answered', payload={'chapter': ...})``

The state matrix entry matches
``COMMAND_HINTS['/续写']``: continuation only makes sense once at least
one chapter draft exists (``WRITING``).
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


class ContinueWritingSkill:
    command = "/续写"
    description = "继续未完成章节"
    requires_states = frozenset({ProjectState.WRITING})
    extra_instructions: str = ""

    async def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        # Lazy import: importing ``writer.engine.events`` at module load
        # would create a cycle (engine.deps imports back into writer.skills).
        # By the time ``run()`` is invoked the engine is fully wired.
        from writer.engine.events import Done, TextChunk

        del deps  # placeholder; consumed by the LLM path coming next
        del ctx
        if not cfg.fast_mode:
            yield TextChunk(text="[engine] /续写 → continue_writing skill\n")
        yield TextChunk(text="[提示] /续写 尚未实现，等待 LLM 接入。\n")
        yield Done(
            reason="command_pending",
            payload={"command": self.command, "todo": "continue_chapter"},
        )


__all__ = ["ContinueWritingSkill"]
