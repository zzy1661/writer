"""Xuanhuan Consultant — a StoryConsultant specialized for 玄幻 / 修真 / fantasy.

Outputs an outline shaped like "境界段: <核心冲突 + 升级目标>".
The chapter prefixes follow the convention documented in
``fea-genre-aware-init/proposal.md`` so downstream ``/目录`` and ``/创作``
can pattern-match on ``境界:`` / ``境界<N>:`` markers.

Like the parent :class:`writer.roles.StoryConsultant`, this is a
deterministic MVP — no network — so the CLI can be exercised end-to-end
without an LLM.
"""

from __future__ import annotations

from pathlib import Path

from writer.config import Settings
from writer.roles.story_consultant import OutlineResult, StoryConsultant


class XuanhuanConsultant(StoryConsultant):
    """Outline consultant for 玄幻 / 修真 / fantasy web-novel."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def draft_outline(
        self,
        idea: str,
        *,
        project_root: Path | None = None,
    ) -> OutlineResult:
        del project_root
        normalized_idea = idea.strip()
        title = self._build_working_title(normalized_idea)

        return OutlineResult(
            title=title,
            premise=normalized_idea,
            chapters=[
                "境界1 炼气期: 觉醒金手指 → 入宗门(或获得传承)",
                "境界2 筑基期: 宗门内比 → 首次外出历练",
                "境界3 金丹期: 副本/秘境 → 同辈/师长级别对手",
                "境界4 元婴期: 大势力登场 → 卷末大高潮",
                "境界5 化神期: 飞升/位面跃迁 → 铺设更高地图",
            ],
        )


__all__ = ["XuanhuanConsultant"]
