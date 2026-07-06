"""Unit tests for ``writer.workflows`` registry dispatch."""

from __future__ import annotations

from pathlib import Path

from writer.engine.context import EngineContext
from writer.workflows import WORKFLOWS, run_workflow
from writer.workflows.write_chapter import run as run_write_chapter


def test_workflows_registry_contains_expected_keys() -> None:
    assert set(WORKFLOWS) == {"write_chapter", "review_chapter"}


def test_workflow_stubs_are_callable() -> None:
    for name, stub in WORKFLOWS.items():
        assert callable(stub), f"{name} should be callable"


def test_run_workflow_returns_chunks_for_known_name() -> None:
    ctx = EngineContext(user_input="some input")

    chunks = list(run_workflow("write_chapter", ctx))

    assert len(chunks) > 0
    assert any("write_chapter" in chunk for chunk in chunks)


def test_write_chapter_langgraph_can_rewrite_once(tmp_path: Path) -> None:
    (tmp_path / "outline").mkdir()
    (tmp_path / "outline" / "toc.md").write_text("1.3 回流测试章", encoding="utf-8")
    ctx = EngineContext(
        user_input="/创作 1.3 触发回流",
        project_root=tmp_path,
        project_state="S2",
        session_id="rewrite-test",
    )

    chunks = run_write_chapter(ctx)
    text = "".join(chunks)

    assert "write_chapter → proofread → review_gate → write_chapter" in text
    assert "retry_count=2" in text


def test_run_workflow_returns_explanatory_chunk_for_unknown_name() -> None:
    ctx = EngineContext(user_input="x")

    chunks = list(run_workflow("nonexistent_workflow", ctx))

    assert len(chunks) == 1
    message = chunks[0]
    assert "未知工作流" in message
    assert "nonexistent_workflow" in message
    # Sorted keys should appear in the explanation
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
        chunks = list(run_workflow("__test_probe__", ctx))
        assert chunks == ["ok"]
        assert captured["ctx"] is ctx
    finally:
        WORKFLOWS.pop("__test_probe__", None)
