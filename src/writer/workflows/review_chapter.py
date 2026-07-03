"""``review_chapter`` workflow stub.

Returns placeholder chunks until multi-reviewer LangGraph pipeline (per
备忘 04 / 06) is wired in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.engine.context import EngineContext


def stub(ctx: EngineContext) -> list[str]:
    """Return placeholder chunks describing what ``review_chapter`` will do."""
    return [
        "[workflow] 占位: review_chapter 阶段启动",
        f"[workflow] session={ctx.session_id or '-'} project_root={ctx.project_root or '-'}",
        "[workflow] TODO: 多 reviewer 并行 + 回流（备忘 04 / 06）",
    ]


__all__ = ["stub"]
