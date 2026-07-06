"""History Consultant — a StoryConsultant specialized for historical fiction.

Outputs an outline shaped like "narrative stage | 史实 anchor | 虚构 note".
The chapter prefixes follow the convention documented in
``fea-genre-aware-init/proposal.md`` so downstream ``/目录`` and ``/创作``
can pattern-match on ``史实:`` / ``虚构:`` markers.

Like the parent :class:`writer.roles.StoryConsultant`, this is a
deterministic MVP — no network — so the CLI can be exercised end-to-end
without an LLM. The class shape mirrors ``StoryConsultant`` so it can
slot into ``EngineDeps.story_consultant`` without ceremony.
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_consultant import OutlineResult, StoryConsultant


class HistoryConsultant(StoryConsultant):
    """Outline consultant for historical fiction (历史 / 架空历史)."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def draft_outline(self, idea: str) -> OutlineResult:
        normalized_idea = idea.strip()
        title = self._build_working_title(normalized_idea)

        return OutlineResult(
            title=title,
            premise=normalized_idea,
            chapters=[
                "前期铺垫: 史实: 朝代/年份与主角出身背景 | 虚构: 主角穿越或登场理由",
                "第一转折: 史实: 重大历史事件锚点（元年/事变）| 虚构: 主角抉择如何介入",
                "中盘深化: 史实: 派系/制度/地理细节 | 虚构: 主角隐藏身份的副作用",
                "代价升级: 史实: 真实人物与权力交锋 | 虚构: 主角承担的风险与代价",
                "终局落幕: 史实: 历史已知的结局 | 虚构: 主角的解释与后续命运",
            ],
        )


__all__ = ["HistoryConsultant"]
