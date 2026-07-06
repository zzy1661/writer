"""Long-task workflows (Plan-Execute-Review graphs, per 备忘 04)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.engine.context import EngineContext

from writer.workflows.review_chapter import stub as review_chapter_stub
from writer.workflows.write_chapter import run as write_chapter_run

WorkflowStub = Callable[["EngineContext"], Iterable[str]]

WORKFLOWS: dict[str, WorkflowStub] = {
    "write_chapter": write_chapter_run,
    "review_chapter": review_chapter_stub,
}


def run_workflow(name: str, ctx: EngineContext) -> Iterable[str]:
    """Dispatch to a registered workflow stub by ``name``.

    Unknown names produce a single explanatory chunk so missing
    registrations are visible in the REPL rather than failing silently.
    """
    runner = WORKFLOWS.get(name)
    if runner is None:
        return [
            f"[workflow] 未知工作流 {name!r}（占位 stub: {sorted(WORKFLOWS)}）"
        ]
    return runner(ctx)


__all__ = ["WORKFLOWS", "WorkflowStub", "run_workflow"]
