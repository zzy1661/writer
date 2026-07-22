"""长任务工作流（Plan-Execute-Review 图，per 备忘 04）。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.runner.context import RunnerContext
    from writer.runner.deps import RunnerDeps
    from writer.workflows.types import WorkflowResult

from writer.workflows.review_chapter import run as review_chapter_run
from writer.workflows.skeleton_chapters import run as skeleton_chapters_run
from writer.workflows.types import WorkflowResult, workflow_result_from_iterable
from writer.workflows.write_chapter import run as write_chapter_run

# 工作流 callable 接受 ``(ctx, deps)`` 并返回
# :class:`WorkflowResult`（PR1+ 契约）。``deps`` 是当前激活的
# :class:`RunnerDeps`，让工作流能调用 ``deps.prose_client``
# 和 ``deps.tool_registry``（per real-writing-pipeline PR2）。
#
# 旧 2-arg 形态（``Callable[[RunnerContext], ...]``）仍被接受以兼容
# 插件；适配器在注册时检查 callable 的签名。
WorkflowStub = Callable[..., "WorkflowResult | Iterable[str]"]

WORKFLOWS: dict[str, WorkflowStub] = {
    "write_chapter": write_chapter_run,
    "review_chapter": review_chapter_run,
    "skeleton_chapters": skeleton_chapters_run,
}


def run_workflow(
    name: str, ctx: RunnerContext, deps: RunnerDeps
) -> WorkflowResult:
    """按 ``name`` 派发到已注册工作流。

    把 ``deps`` 传给工作流 callable，让 PR2+ 工作流可以调用
    ``deps.prose_client.generate_text(...)`` 和
    ``deps.tool_registry.invoke(...)``。未知名称产出
    ``WorkflowResult(status="failed", ...)``，让引擎的
    :func:`_run_workflow` 将其作为 ``Done(aborted)`` 暴露。

    仅接受 ``(ctx,)``（PR1 形态）的旧 callable 通过
    :func:`inspect.signature` introspection 仍受支持；那种情况下
    ``deps`` 被静默丢弃。
    """
    runner = WORKFLOWS.get(name)
    if runner is None:
        available = sorted(WORKFLOWS)
        return workflow_result_from_iterable(
            [f"[workflow] 未知工作流 {name!r}（占位 stub: {available}）"],
            status="failed",
            metrics={"error": "unknown_workflow", "available": ", ".join(available)},
        )

    import inspect

    try:
        sig = inspect.signature(runner)
        takes_deps = len(sig.parameters) >= 2
    except (TypeError, ValueError):
        takes_deps = False

    raw = runner(ctx, deps) if takes_deps else runner(ctx)  # type: ignore[call-arg]

    if isinstance(raw, WorkflowResult):
        return raw
    return workflow_result_from_iterable(raw, status="pending")


__all__ = [
    "WORKFLOWS",
    "WorkflowResult",
    "WorkflowStub",
    "run_workflow",
    "skeleton_chapters_run",
    "workflow_result_from_iterable",
]
