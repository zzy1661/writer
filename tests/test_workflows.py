"""Unit tests for ``writer.workflows`` registry dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from writer.llm.prose import RealProseClient
from writer.runner.context import RunnerContext
from writer.runner.deps import RunnerDeps, production_deps
from writer.workflows import WORKFLOWS, WorkflowResult, run_workflow
from writer.workflows.write_chapter import run as run_write_chapter

# 自 2026-07-14 起,plan_chapter 严格 LLM 驱动。本文件内联最小 fake
# LLM + deps 工厂,避免与 ``test_workflows_write_chapter`` 共享测试
# 助手(跨文件 import 在 pytest 下需要 ``tests/__init__.py``,
# 项目并无此约定)。


class _MiniRecordingChatModel(BaseChatModel):
    """最小 fake LLM —— plan / draft / review 三次调用都返回 pass。"""

    call_count: int = 0

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "mini-recording-fake"

    def _generate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        self.call_count += 1
        # ``invoke_structured_json`` 在 messages 前置一个
        # ``_json_contract_message`` 系统消息,所以「审核节点」不一定
        # 在 ``messages[0]``。扫描所有消息体。
        joined = "\n".join(m.content or "" for m in messages)
        is_review = "审核节点" in joined
        content = (
            '{"pass": true, "score": 8, "concerns": []}'
            if is_review
            else "stub real draft content " * 30
        )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    async def _agenerate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _make_real_prose_deps() -> RunnerDeps:
    deps = production_deps()
    llm = _MiniRecordingChatModel()
    deps.prose_client = RealProseClient(llm=llm)
    deps.review_llm = llm
    return deps


def test_workflows_registry_contains_expected_keys() -> None:
    assert set(WORKFLOWS) == {"write_chapter", "review_chapter"}


def test_workflow_stubs_are_callable() -> None:
    for name, stub in WORKFLOWS.items():
        assert callable(stub), f"{name} should be callable"


def test_run_workflow_returns_chunks_for_known_name() -> None:
    ctx = RunnerContext(user_input="some input")
    deps = _make_real_prose_deps()

    result = run_workflow("write_chapter", ctx, deps)

    # PR1: ``run_workflow`` returns a ``WorkflowResult``; consumers
    # access ``.chunks`` instead of iterating the return value.
    assert isinstance(result, WorkflowResult)
    assert len(result.chunks) > 0
    assert any("write_chapter" in chunk for chunk in result.chunks)


def test_write_chapter_langgraph_can_rewrite_once(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
    (tmp_path / "大纲").mkdir()
    (tmp_path / "大纲" / "章节目录.md").write_text("1.3 回流测试章", encoding="utf-8")
    ctx = RunnerContext(
        user_input="/创作 1.3 触发回流",
        project_root=tmp_path,
        project_state="S2",
        session_id="rewrite-test",
    )
    deps = production_deps(project_root=tmp_path)
    deps = _make_real_prose_deps()

    result = run_write_chapter(ctx, deps)
    text = "".join(result.chunks)

    # PR2: 5-node graph produces a longer trace than the PR1 4-node
    # version; the rewrite loop is still observable via retry_count.
    assert "draft_chapter" in text
    assert "review_gate" in text
    assert "retry_count" in text


def test_run_workflow_returns_failed_result_for_unknown_name() -> None:
    ctx = RunnerContext(user_input="x")
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
    """The stub receives the same RunnerContext we pass to run_workflow."""
    captured: dict[str, RunnerContext] = {}

    def fake_stub(ctx: RunnerContext) -> list[str]:
        captured["ctx"] = ctx
        return ["ok"]

    WORKFLOWS["__test_probe__"] = fake_stub
    try:
        ctx = RunnerContext(user_input="probe", session_id="sid-123")
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
