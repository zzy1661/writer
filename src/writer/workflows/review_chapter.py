"""``review_chapter`` workflow stub.

Returns placeholder chunks until multi-reviewer LangGraph pipeline (per
备忘 04 / 06) is wired in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.engine.context import EngineContext


def stub(ctx: EngineContext) -> list[str]:
    """Return placeholder chunks describing what ``review_chapter`` will do.

    Note: this is a **stub**. It does not yet run the multi-reviewer
    pipeline (per 备忘 04 / 06); the engine still surfaces a
    ``Done(reason='workflow_pending')`` afterwards so callers know the
    workflow is not real.
    """
    return [
        "[workflow] (stub) review_chapter 阶段启动",
        f"[workflow] (stub) session={ctx.session_id or '-'} project_root={ctx.project_root or '-'}",
        "[workflow] (stub) 多 reviewer 并行 + 回流图未落地；不会产生审核。",
    ]


__all__ = ["stub"]
