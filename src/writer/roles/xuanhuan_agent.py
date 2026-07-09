"""Xuanhuan Agent — a StoryAgent specialized for 玄幻 / 修真 / fantasy.

Dispatches ``PromptKey(role="outline", genre="玄幻")`` through the parent
:class:`writer.roles.StoryAgent`, which fetches the xuanhuan-aware
system prompt from the centralised
:mod:`writer.prompts.registry`. When the LLM is unavailable, the parent
falls back to :data:`writer.prompts.FALLBACK_OUTLINE_CHAPTERS['玄幻']`
— five 境界 nodes that downstream ``/目录`` and ``/创作`` pattern-match
on via the ``境界:`` prefix.

Renamed from ``XuanhuanConsultant`` to ``XuanhuanAgent`` per
``fea-agent-mirror``; the contract is unchanged.
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_agent import StoryAgent


class XuanhuanAgent(StoryAgent):
    """Outline agent for 玄幻 / 修真 / fantasy web-novel."""

    GENRE = "玄幻"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)


__all__ = ["XuanhuanAgent"]
