"""Romance Consultant — a StoryConsultant specialized for 言情 (romance).

Dispatches ``PromptKey(role="outline", genre="言情")`` through the parent
:class:`writer.roles.StoryConsultant`, which fetches the romance-aware
system prompt from the centralised
:mod:`writer.prompts.registry`. When the LLM is unavailable, the parent
falls back to :data:`writer.prompts.FALLBACK_OUTLINE_CHAPTERS['言情']`
— nine GMC beats that downstream ``/目录`` and ``/创作`` pattern-match on
via the ``节拍:`` prefix.
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_consultant import StoryConsultant


class RomanceConsultant(StoryConsultant):
    """Outline consultant for 言情 (romance web-novel)."""

    GENRE = "言情"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)


__all__ = ["RomanceConsultant"]
