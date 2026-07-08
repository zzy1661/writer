"""Xuanhuan Consultant — a StoryConsultant specialized for 玄幻 / 修真 / fantasy.

Dispatches ``PromptKey(role="outline", genre="玄幻")`` through the parent
:class:`writer.roles.StoryConsultant`, which fetches the xuanhuan-aware
system prompt from the centralised
:mod:`writer.prompts.registry`. When the LLM is unavailable, the parent
falls back to :data:`writer.prompts.FALLBACK_OUTLINE_CHAPTERS['玄幻']`
— five 境界 nodes that downstream ``/目录`` and ``/创作`` pattern-match
on via the ``境界:`` prefix.
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_consultant import StoryConsultant


class XuanhuanConsultant(StoryConsultant):
    """Outline consultant for 玄幻 / 修真 / fantasy web-novel."""

    GENRE = "玄幻"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)


__all__ = ["XuanhuanConsultant"]
