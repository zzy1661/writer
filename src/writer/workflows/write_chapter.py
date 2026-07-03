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
    """Return placeholder chunks describing what ``write_chapter`` will do."""
    return [
        "[workflow] 占位: write_chapter 阶段启动",
        f"[workflow] session={ctx.session_id or '-'} project_root={ctx.project_root or '-'}",
        "[workflow] TODO: LangGraph Plan-Execute-Review 图（备忘 04）",
    ]


__all__ = ["stub"]
