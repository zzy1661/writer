"""``write_chapter`` workflow stub.

Returns placeholder chunks until the LangGraph Plan-Execute-Review graph
(per 备忘 04) is wired in. The stub keeps a fixed shape so the engine can
already test streaming behavior end-to-end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.engine.context import EngineContext


def stub(ctx: EngineContext) -> list[str]:
    """Return placeholder chunks describing what ``write_chapter`` will do.

    Note: this is a **stub**. It does not yet invoke the LangGraph
    Plan-Execute-Review graph (per 备忘 04); the engine still surfaces a
    ``Done(reason='workflow_pending')`` afterwards so callers know the
    workflow is not real. Kept short on purpose to avoid the earlier
    "TODO" leak that confused users into thinking writing had actually
    started.
    """
    return [
        "[workflow] (stub) write_chapter 阶段启动",
        f"[workflow] (stub) session={ctx.session_id or '-'} project_root={ctx.project_root or '-'}",
        "[workflow] (stub) LangGraph 图未落地；不会产生正文。",
    ]


__all__ = ["stub"]
