"""Long-task workflows (Plan-Execute-Review graphs, per 备忘 04)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps
    from writer.workflows.types import WorkflowResult

from writer.workflows.review_chapter import run as review_chapter_run
from writer.workflows.types import WorkflowResult, workflow_result_from_iterable
from writer.workflows.write_chapter import run as write_chapter_run

# Workflow callables take ``(ctx, deps)`` and return
# :class:`WorkflowResult` (PR1+ contract). ``deps`` is the active
# :class:`EngineDeps` so the workflow can call ``deps.prose_client``
# and ``deps.tool_registry`` (per real-writing-pipeline PR2).
#
# Older 2-arg shapes (``Callable[[EngineContext], ...]``) are still
# accepted for plugin compatibility; the adapter inspects the
# callable's signature at registration time.
WorkflowStub = Callable[..., "WorkflowResult | Iterable[str]"]

WORKFLOWS: dict[str, WorkflowStub] = {
    "write_chapter": write_chapter_run,
    "review_chapter": review_chapter_run,
}


def run_workflow(
    name: str, ctx: EngineContext, deps: EngineDeps
) -> WorkflowResult:
    """Dispatch to a registered workflow by ``name``.

    Passes ``deps`` to the workflow callable so PR2+ workflows can
    call ``deps.prose_client.generate_text(...)`` and
    ``deps.tool_registry.invoke(...)``. Unknown names produce
    ``WorkflowResult(status="failed", ...)`` so the engine's
    :func:`_run_workflow` surfaces them as ``Done(aborted)``.

    Legacy callables that accept only ``(ctx,)`` (the PR1 shape) are
    still supported via :func:`inspect.signature` introspection;
    ``deps`` is dropped silently in that case.
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
    "workflow_result_from_iterable",
]
