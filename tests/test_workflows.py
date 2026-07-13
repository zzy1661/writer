"""Unit tests for ``writer.workflows`` registry dispatch."""

from __future__ import annotations

from pathlib import Path

from writer.engine.context import EngineContext
from writer.engine.deps import production_deps
from writer.workflows import WORKFLOWS, WorkflowResult, run_workflow
from writer.workflows.write_chapter import run as run_write_chapter


def test_workflows_registry_contains_expected_keys() -> None:
    assert set(WORKFLOWS) == {"write_chapter", "review_chapter"}


def test_workflow_stubs_are_callable() -> None:
    for name, stub in WORKFLOWS.items():
        assert callable(stub), f"{name} should be callable"


def test_run_workflow_returns_chunks_for_known_name() -> None:
    ctx = EngineContext(user_input="some input")
    deps = production_deps()

    result = run_workflow("write_chapter", ctx, deps)

    # PR1: ``run_workflow`` returns a ``WorkflowResult``; consumers
    # access ``.chunks`` instead of iterating the return value.
    assert isinstance(result, WorkflowResult)
    assert len(result.chunks) > 0
    assert any("write_chapter" in chunk for chunk in result.chunks)


def test_write_chapter_langgraph_can_rewrite_once(tmp_path: Path) -> None:
    (tmp_path / "大纲").mkdir()
    (tmp_path / "大纲" / "章节目录.md").write_text("1.3 回流测试章", encoding="utf-8")
    ctx = EngineContext(
        user_input="/创作 1.3 触发回流",
        project_root=tmp_path,
        project_state="S2",
        session_id="rewrite-test",
    )
    deps = production_deps(project_root=tmp_path)

    result = run_write_chapter(ctx, deps)
    text = "".join(result.chunks)

    # PR2: 5-node graph produces a longer trace than the PR1 4-node
    # version; the rewrite loop is still observable via retry_count.
    assert "draft_chapter" in text
    assert "review_gate" in text
    assert "retry_count" in text


def test_run_workflow_returns_failed_result_for_unknown_name() -> None:
    ctx = EngineContext(user_input="x")
    deps = production_deps()

    result = run_workflow("nonexistent_workflow", ctx, deps)

    # PR1 contract: unknown name -> WorkflowResult(status="failed", ...)
    # so the engine surfaces Done(aborted). The error message lives
    # in the first chunk; the registry also surfaces available keys.
    assert result.status == "failed"
    assert result.metrics.get("error") == "unknown_workflow"
    assert len(result.chunks) == 1
    message = result.chunks[0]
    assert "未知工作流" in message
    assert "nonexistent_workflow" in message
    for key in sorted(WORKFLOWS):
        assert key in message


def test_run_workflow_passes_context_to_stub() -> None:
    """The stub receives the same EngineContext we pass to run_workflow."""
    captured: dict[str, EngineContext] = {}

    def fake_stub(ctx: EngineContext) -> list[str]:
        captured["ctx"] = ctx
        return ["ok"]

    WORKFLOWS["__test_probe__"] = fake_stub
    try:
        ctx = EngineContext(user_input="probe", session_id="sid-123")
        deps = production_deps()
        result = run_workflow("__test_probe__", ctx, deps)
        # PR1: legacy ``Iterable[str]`` callables are wrapped into
        # ``WorkflowResult(status="pending", chunks=...)`` so the test
        # now checks the chunks list and the captured context.
        assert result.chunks == ("ok",)
        assert result.status == "pending"
        assert captured["ctx"] is ctx
    finally:
        WORKFLOWS.pop("__test_probe__", None)
