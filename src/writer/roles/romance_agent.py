"""Romance Agent — a StoryAgent specialized for 言情 (romance).

Dispatches ``PromptKey(role="outline", genre="言情")`` through the parent
:class:`writer.roles.StoryAgent`, which fetches the romance-aware
system prompt from the centralised
:mod:`writer.prompts.registry`. When the LLM is unavailable, the parent
falls back to :data:`writer.prompts.FALLBACK_OUTLINE_CHAPTERS['言情']`
— nine GMC beats that downstream ``/目录`` and ``/创作`` pattern-match on
via the ``节拍:`` prefix.

Renamed from ``RomanceConsultant`` to ``RomanceAgent`` per
``fea-agent-mirror``; the contract is unchanged.
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_agent import StoryAgent


class RomanceAgent(StoryAgent):
    """Outline agent for 言情 (romance web-novel)."""

    GENRE = "言情"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)


__all__ = ["RomanceAgent"]
