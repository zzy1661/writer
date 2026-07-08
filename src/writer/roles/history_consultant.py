"""History Consultant — a StoryConsultant specialized for historical fiction.

Dispatches ``PromptKey(role="outline", genre="历史")`` through the parent
:class:`writer.roles.StoryConsultant`, which fetches the history-aware
system prompt from the centralised
:mod:`writer.prompts.registry`. When the LLM is unavailable, the parent
falls back to :data:`writer.prompts.FALLBACK_OUTLINE_CHAPTERS['历史']`
— a five-stage outline with the ``史实:`` / ``虚构:`` markers that
downstream ``/目录`` and ``/创作`` pattern-match on.

The class shape mirrors :class:`writer.roles.StoryConsultant` so it can
slot into ``EngineDeps.story_consultant`` without ceremony.
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_consultant import StoryConsultant


class HistoryConsultant(StoryConsultant):
    """Outline consultant for historical fiction (历史 / 架空历史)."""

    GENRE = "历史"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)


__all__ = ["HistoryConsultant"]
