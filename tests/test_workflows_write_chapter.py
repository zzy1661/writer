"""Tests for the rewritten ``write_chapter`` 5-node LangGraph workflow.

Added 2026-07-09 (real-writing-pipeline PR2) — covers the
``prep_context → plan_chapter → draft_chapter → proofread →
review_gate → (rewrite | persist_outputs)`` graph, including
the prose_client integration, review gate threshold (7), retry
loop, and persistence side effects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from writer.llm.prose import (
    DeterministicProseClient,
    RealProseClient,
)
from writer.runner.context import RunnerContext
from writer.runner.deps import RunnerDeps, production_deps
from writer.workflows import WorkflowResult
from writer.workflows.write_chapter import (
    REVIEW_THRESHOLD,
    ReviewVerdict,
    build_writer_graph,
    run,
    stub,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _RecordingChatModel(BaseChatModel):
    """Fake ``BaseChatModel`` that records calls and returns canned content.

    ``response_factory`` lets each test return a different
    ``AIMessage`` for the prose vs. review LLM calls.

    自 2026-07-14（plan_chapter LLM 驱动）新增：
        - ``call_count`` 跟踪 invoke 次数
        - ``plan_calls`` 收集 plan_chapter 节点的 (system, user) 元组，
          让测试可断言计划节点真的调了 LLM
    """

    last_messages: list = []  # type: ignore[type-arg]
    response_factory: Any = None
    raise_on_invoke: Exception | None = None
    call_count: int = 0
    plan_calls: list = []  # type: ignore[type-arg]
    review_calls: list = []  # type: ignore[type-arg]

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def _generate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        self.call_count += 1
        self.last_messages = list(messages)
        # ``plan_chapter`` 的 system + user 来自
        # ``CHAPTER_PLAN_TEMPLATE``：user 含 ``chapter_id=`` 行。
        # 仅 plan_chapter 调 generate_text；draft 也走同一 channel，
        # 我们按 system prompt 是否含「规划节点」字样区分。
        is_plan = bool(messages) and "规划节点" in (messages[0].content or "")
        is_review = bool(messages) and "审核节点" in (messages[0].content or "")
        if is_plan:
            self.plan_calls.append(
                {
                    "system": messages[0].content if messages else "",
                    "user": messages[1].content if len(messages) > 1 else "",
                }
            )
        elif is_review:
            self.review_calls.append(
                {
                    "system": messages[0].content if messages else "",
                    "user": messages[1].content if len(messages) > 1 else "",
                }
            )
        if self.raise_on_invoke is not None:
            raise self.raise_on_invoke
        response = self.response_factory() if self.response_factory else AIMessage(
            content="fallback"
        )
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _build_fake_prose_response(text: str) -> AIMessage:
    return AIMessage(content=text)


def _build_fake_review_verdict(
    *, pass_: bool, score: int, concerns: list[str] | None = None
) -> AIMessage:
    """Build an ``AIMessage`` whose content is JSON matching ReviewVerdict."""
    return AIMessage(
        content=json.dumps(
            {"pass": pass_, "score": score, "concerns": concerns or []},
            ensure_ascii=False,
        )
    )


def _stub_prose_client(text: str = "stub draft content") -> MagicMock:
    """A fake ``LLMProseClient`` that returns ``text`` without an LLM call."""
    client = MagicMock(spec=DeterministicProseClient)
    client.name = "deterministic"
    client.generate_text.return_value = text
    return client


def _make_deps_with_prose(
    prose_text: str = "stub draft content",
    *,
    prose_name: str = "deterministic",
) -> RunnerDeps:
    """Build an RunnerDeps with a recording-fake prose client."""
    deps = production_deps()
    deps.prose_client = _stub_prose_client(prose_text)
    deps.prose_client.name = prose_name  # type: ignore[attr-defined]
    return deps


def _make_deps_with_real_prose(llm: _RecordingChatModel) -> RunnerDeps:
    """Build an RunnerDeps with a real RealProseClient wrapping ``llm``.

    Also wires ``deps.review_llm = llm`` so the review path uses
    the same recording fake — production wiring uses
    :func:`writer.llm.provider.get_llm` but the test path must NOT
    require an API key.
    """
    deps = production_deps()
    deps.prose_client = RealProseClient(llm=llm)
    deps.review_llm = llm
    return deps


def _recording_llm_for_happy_path(
    *, plan_text: str = "stub plan content", draft_text: str = "very long draft content " * 30
) -> _RecordingChatModel:
    """构造一个写 plan → draft → review(pass) → persist_outputs 通路的 fake LLM。

    返回的 ``_RecordingChatModel`` 配置好 :attr:`response_factory`,
    让三次连续 LLM 调用各自返回合适的 AIMessage:第 1 次是 plan 散文,
    第 2 次是 draft 散文,第 3 次是 score=8 的 review verdict(自动 pass)。
    """
    llm = _RecordingChatModel()
    calls = {"n": 0}

    def factory() -> AIMessage:
        calls["n"] += 1
        if calls["n"] == 1:
            return _build_fake_prose_response(plan_text)
        if calls["n"] == 2:
            return _build_fake_prose_response(draft_text)
        return _build_fake_review_verdict(pass_=True, score=8)

    llm.response_factory = factory
    return llm


# ---------------------------------------------------------------------------
# Tests: ReviewVerdict model
# ---------------------------------------------------------------------------


class TestReviewVerdictModel:
    def test_minimal_pass(self) -> None:
        verdict = ReviewVerdict.model_validate({"pass": True, "score": 8})
        assert verdict.pass_ is True
        assert verdict.score == 8
        assert verdict.concerns == []

    def test_with_concerns(self) -> None:
        verdict = ReviewVerdict.model_validate(
            {"pass": False, "score": 4, "concerns": ["F003 timing"]}
        )
        assert verdict.pass_ is False
        assert verdict.score == 4
        assert verdict.concerns == ["F003 timing"]

    def test_score_clamps_to_0_10(self) -> None:
        with pytest.raises(ValueError):
            ReviewVerdict.model_validate({"pass": True, "score": 11})
        with pytest.raises(ValueError):
            ReviewVerdict.model_validate({"pass": True, "score": -1})

    def test_threshold_is_7(self) -> None:
        assert REVIEW_THRESHOLD == 7


# ---------------------------------------------------------------------------
# Tests: Graph topology
# ---------------------------------------------------------------------------


class TestGraphTopology:
    def test_graph_compiles(self) -> None:
        graph = build_writer_graph()
        assert graph is not None

    def test_graph_has_six_nodes(self) -> None:
        # prep_context, plan_chapter, draft_chapter, proofread,
        # review_gate, persist_outputs — 6 nodes.
        graph = build_writer_graph()
        # LangGraph exposes the graph spec via .get_graph(); nodes is
        # accessible on the underlying spec.
        nodes = list(graph.get_graph().nodes.keys())
        assert "prep_context" in nodes
        assert "plan_chapter" in nodes
        assert "draft_chapter" in nodes
        assert "proofread" in nodes
        assert "review_gate" in nodes
        assert "persist_outputs" in nodes

    def test_graph_traverses_5_nodes_in_happy_path(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path()
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # 真实 LLM 路径：plan_chapter 调一次 LLM，draft_chapter 调一次，
        # review_gate 调一次并以 score 8 通过；graph 抵达 persist_outputs。
        text = "".join(result.chunks)
        assert "prep_context" in text
        assert "plan_chapter" in text
        assert "draft_chapter" in text
        assert "proofread" in text
        assert "review_gate" in text
        assert "persist_outputs" in text
        # plan_chapter 节点真的调过 LLM。
        assert len(llm.plan_calls) == 1

    def test_happy_path_writes_draft_to_manuscript(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        draft_text = "deterministic draft text " * 20
        llm = _recording_llm_for_happy_path(draft_text=draft_text)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert result.status == "completed"
        # ``artifacts["draft_path"]`` is set; the file exists on disk.
        assert "draft_path" in result.artifacts
        draft_path = result.artifacts["draft_path"]
        assert draft_path.exists()
        assert draft_path.read_text(encoding="utf-8") == draft_text

    def test_happy_path_writes_chapter_summaries(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        draft_text = "摘要测试内容 " * 20
        llm = _recording_llm_for_happy_path(draft_text=draft_text)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert "summaries_path" in result.artifacts
        summaries_path = result.artifacts["summaries_path"]
        assert summaries_path.exists()
        payload = json.loads(summaries_path.read_text(encoding="utf-8"))
        assert any(c["chapter_id"] == "1.1" for c in payload["chapters"])

    def test_workflow_result_carries_score_metric(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="draft " * 30)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # Real 路径以 score 8 通过 review_gate。
        assert result.metrics.get("score") == 8
        assert result.metrics.get("retry_count") == 1


# ---------------------------------------------------------------------------
# Tests: Retry loop
# ---------------------------------------------------------------------------


class TestRetryLoop:
    def test_real_mode_loops_on_low_score(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        # ``RealProseClient`` for prose + recording LLM that returns
        # score=4 (below threshold 7). The graph must loop back to
        # draft_chapter and retry.
        llm = _RecordingChatModel()
        # First message is the prose call; subsequent are the
        # review call. We always return low-score verdict.
        call_count = {"n": 0}

        def factory() -> AIMessage:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _build_fake_prose_response("first draft " * 30)
            return _build_fake_review_verdict(pass_=False, score=4, concerns=["bad"])

        llm.response_factory = factory
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        text = "".join(result.chunks)
        # The loop runs the initial draft + 1 retry (cap is
        # ``retry_count < max_retries`` = ``1 < 2`` for the first
        # retry, ``2 < 2`` is False for the second). So we see 2
        # draft_chapter invocations + 1 persist_outputs run.
        assert text.count("draft_chapter") == 2
        assert "persist_outputs" in text
        assert result.metrics.get("retry_count") == 2

    def test_max_retries_caps_the_loop(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _RecordingChatModel()
        # Always return a low-score verdict.
        llm.response_factory = lambda: _build_fake_review_verdict(
            pass_=False, score=3
        )
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # Even with always-low scores, the loop must terminate.
        assert result.status == "completed"
        # retry_count should be capped at max_retries=2 + 1 initial
        # attempt = 3 total draft_chapter invocations.
        text = "".join(result.chunks)
        assert text.count("draft_chapter") <= 3


# ---------------------------------------------------------------------------
# Tests: WorkflowResult shape
# ---------------------------------------------------------------------------


class TestWorkflowResultShape:
    def test_completed_status(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="a" * 300)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert isinstance(result, WorkflowResult)
        assert result.status == "completed"

    def test_chunks_are_a_tuple(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="a" * 300)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert isinstance(result.chunks, tuple)
        assert len(result.chunks) > 0

    def test_metrics_have_score_and_retry_count(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="a" * 300)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert "score" in result.metrics
        assert "retry_count" in result.metrics

    def test_artifacts_include_draft_path(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="a" * 300)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert "draft_path" in result.artifacts
        assert isinstance(result.artifacts["draft_path"], Path)


# ---------------------------------------------------------------------------
# Tests: plan_chapter LLM-driven behavior (per 2026-07-14)
# ---------------------------------------------------------------------------


class TestPlanChapterLLM:
    def test_plan_chapter_node_raises_when_deterministic(self, tmp_path: Path) -> None:
        """deterministic prose_client 调 plan_chapter 必须 raise。

        单独测 ``_plan_chapter_node`` 节点,不通过 graph invoke。注入
        ``DeterministicProseClient`` 后直接调节点函数;期望 RuntimeError,
        其 message 提示用户配 ``WRITER_API_KEY``。
        """
        from writer.llm.prose import DeterministicProseClient
        from writer.workflows.write_chapter import (
            _plan_chapter_node,
            _reset_deps,
            _set_deps,
        )

        deps = production_deps()
        deps.prose_client = DeterministicProseClient()
        state = {
            "chapter_id": "1.1",
            "task": "/创作 1.1",
            "requirements": [],
            "context": {"canon_block": "正典", "history_block": "前情"},
            "trace": [],
        }
        _set_deps(deps)
        try:
            with pytest.raises(RuntimeError, match="plan_chapter 需要真实 LLM"):
                _plan_chapter_node(state)  # type: ignore[arg-type]
        finally:
            _reset_deps()

    def test_plan_chapter_node_invokes_prose_client(self, tmp_path: Path) -> None:
        """real 模式下 plan_chapter 节点调 LLM 一次,plan 字段写入返回值。

        单独测 ``_plan_chapter_node`` + ``_call_plan_chapter``,不通过
        graph invoke。注入 fake LLM,断言 prose_client.generate_text 被
        调一次且 plan 字段被写为 LLM 返回的散文。
        """
        from writer.workflows.write_chapter import (
            _plan_chapter_node,
            _reset_deps,
            _set_deps,
        )

        llm = _RecordingChatModel()
        llm.response_factory = lambda: _build_fake_prose_response(
            "本章核心冲突:主角与对手的路线分歧"
        )
        deps = production_deps()
        deps.prose_client = RealProseClient(llm=llm)
        deps.review_llm = llm
        state = {
            "chapter_id": "1.1",
            "task": "/创作 1.1",
            "requirements": ["突出冲突", "结尾留钩"],
            "context": {
                "canon_block": "正典片段",
                "history_block": "前情片段",
            },
            "trace": [],
        }
        _set_deps(deps)
        try:
            new_state = _plan_chapter_node(state)  # type: ignore[arg-type]
        finally:
            _reset_deps()

        assert "plan" in new_state
        assert "主角与对手" in new_state["plan"]
        assert new_state["trace"][-1] == "plan_chapter"
        # LLM 确实被调用了一次,且 system 来自 CHAPTER_PLAN_TEMPLATE。
        assert len(llm.plan_calls) == 1
        assert "规划节点" in llm.plan_calls[0]["system"]
        assert "chapter_id=1.1" in llm.plan_calls[0]["user"]
        assert "突出冲突" in llm.plan_calls[0]["user"]


# ---------------------------------------------------------------------------
# Tests: Parameter parsing integration
# ---------------------------------------------------------------------------


class TestArgsIntegration:
    def test_chapter_id_extracted_from_user_input(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="a" * 300)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 2.3 突出冲突",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # The chapter file is written under 草稿/chapter-2.3.md.
        assert "chapter-2.3.md" in str(result.artifacts["draft_path"])

    def test_requirements_passed_to_prose_client(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="a" * 300)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1 突出冲突 结尾留钩",
            project_root=tmp_path,
            project_state="S2",
        )
        run(ctx, deps)
        # Real 路径：plan_chapter 真的被 LLM 调过且 user prompt 含 requirements。
        assert len(llm.plan_calls) == 1
        user = llm.plan_calls[0]["user"]
        assert "突出冲突" in user
        assert "结尾留钩" in user

    def test_rewrite_flag_triggers_extra_loop(self, tmp_path: Path) -> None:
        # When the user input contains "回流" or "重写", the
        # review_gate forces a rewrite (independent of LLM score).
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        llm = _recording_llm_for_happy_path(draft_text="a" * 300)
        deps = _make_deps_with_real_prose(llm)
        ctx = RunnerContext(
            user_input="/创作 1.1 请回流重写",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # rewrite=True forces the loop; retry_count should reflect
        # the additional attempt(s).
        assert result.metrics.get("retry_count", 0) >= 1


# ---------------------------------------------------------------------------
# Tests: Stub alias
# ---------------------------------------------------------------------------


class TestStubAlias:
    def test_stub_raises_not_implemented(self) -> None:
        # The PR1 ``stub`` compatibility alias is no longer a real
        # workflow; it raises so callers know to use ``run``.
        with pytest.raises(NotImplementedError):
            stub(MagicMock(spec=RunnerContext))
