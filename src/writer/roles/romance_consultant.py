"""Romance Consultant — a StoryConsultant specialized for 言情 (romance).

Outputs an outline shaped like "节拍<N>: <GMC 阶段>" — 8 to 12 emotional
beats following the Romancing the Beat / GMC convention documented in
``fea-genre-aware-init/proposal.md``. The chapter prefixes follow that
convention so downstream ``/目录`` and ``/创作`` can pattern-match on
``节拍:`` / ``GMC:`` markers.

Like the parent :class:`writer.roles.StoryConsultant`, this is a
deterministic MVP — no network — so the CLI can be exercised end-to-end
without an LLM.
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_consultant import OutlineResult, StoryConsultant


class RomanceConsultant(StoryConsultant):
    """Outline consultant for 言情 (romance web-novel)."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def draft_outline(self, idea: str) -> OutlineResult:
        normalized_idea = idea.strip()
        title = self._build_working_title(normalized_idea)

        return OutlineResult(
            title=title,
            premise=normalized_idea,
            chapters=[
                "节拍1: 相遇 → 第一印象 → 巧合接触",
                "节拍2: 吸引 → 主动互动 → 共处升温",
                "节拍3: 暧昧 → 错觉甜蜜 → 内心骚动",
                "节拍4: 误会 → 信息差/第三者破坏 → 关系骤冷",
                "节拍5: 内部障碍 → 主角情感创伤/价值观冲突",
                "节拍6: 分离危机 → 外部压力下的分别",
                "节拍7: 自我觉醒 → 主角主动解决自身障碍",
                "节拍8: 表白/和解 → 关系转换 → 承诺",
                "节拍9: 余韵 → 关系稳定 → 长线钩子",
            ],
        )


__all__ = ["RomanceConsultant"]
