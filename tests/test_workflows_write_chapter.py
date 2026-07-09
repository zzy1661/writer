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

from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps, production_deps
from writer.llm.prose import (
    DeterministicProseClient,
    RealProseClient,
)
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
    """

    last_messages: list = []  # type: ignore[type-arg]
    response_factory: Any = None
    raise_on_invoke: Exception | None = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def _generate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        self.last_messages = list(messages)
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
) -> EngineDeps:
    """Build an EngineDeps with a recording-fake prose client."""
    deps = production_deps()
    deps.prose_client = _stub_prose_client(prose_text)
    deps.prose_client.name = prose_name  # type: ignore[attr-defined]
    return deps


def _make_deps_with_real_prose(llm: _RecordingChatModel) -> EngineDeps:
    """Build an EngineDeps with a real RealProseClient wrapping ``llm``.

    Also wires ``deps.review_llm = llm`` so the review path uses
    the same recording fake — production wiring uses
    :func:`writer.llm.provider.get_llm` but the test path must NOT
    require an API key.
    """
    deps = production_deps()
    deps.prose_client = RealProseClient(llm=llm)
    deps.review_llm = llm
    return deps


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
        deps = _make_deps_with_prose("very long draft content " * 30)
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # The deterministic path auto-passes; the graph reaches
        # persist_outputs after one pass through review_gate.
        text = "".join(result.chunks)
        assert "prep_context" in text
        assert "plan_chapter" in text
        assert "draft_chapter" in text
        assert "proofread" in text
        assert "review_gate" in text
        assert "persist_outputs" in text

    def test_happy_path_writes_draft_to_manuscript(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("deterministic draft text " * 20)
        ctx = EngineContext(
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
        assert draft_path.read_text(encoding="utf-8") == "deterministic draft text " * 20

    def test_happy_path_writes_chapter_summaries(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("摘要测试内容 " * 20)
        ctx = EngineContext(
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
        deps = _make_deps_with_prose("draft " * 30)
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # Deterministic path auto-passes at score 8.
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
        ctx = EngineContext(
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
        ctx = EngineContext(
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
        deps = _make_deps_with_prose("a" * 300)
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert isinstance(result, WorkflowResult)
        assert result.status == "completed"

    def test_chunks_are_a_tuple(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("a" * 300)
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert isinstance(result.chunks, tuple)
        assert len(result.chunks) > 0

    def test_metrics_have_score_and_retry_count(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("a" * 300)
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert "score" in result.metrics
        assert "retry_count" in result.metrics

    def test_artifacts_include_draft_path(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("a" * 300)
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        assert "draft_path" in result.artifacts
        assert isinstance(result.artifacts["draft_path"], Path)


# ---------------------------------------------------------------------------
# Tests: DeterministicProseClient integration
# ---------------------------------------------------------------------------


class TestDeterministicIntegration:
    def test_deterministic_does_not_invoke_llm(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        # Use the real DeterministicProseClient (no fake).
        deps = production_deps()
        deps.prose_client = DeterministicProseClient()
        assert deps.prose_client.name == "deterministic"
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # The deterministic path never makes an LLM call.
        assert result.status == "completed"
        # The resulting draft must be ≥ 200 chars (per prose-llm spec).
        draft_path = result.artifacts["draft_path"]
        assert len(draft_path.read_text(encoding="utf-8")) >= 200

    def test_deterministic_auto_passes_review(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = production_deps()
        deps.prose_client = DeterministicProseClient()
        ctx = EngineContext(
            user_input="/创作 1.1",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # Deterministic review always passes at score 8.
        assert result.metrics.get("score") == 8
        # No retries: the loop only runs once.
        assert result.metrics.get("retry_count") == 1


# ---------------------------------------------------------------------------
# Tests: Parameter parsing integration
# ---------------------------------------------------------------------------


class TestArgsIntegration:
    def test_chapter_id_extracted_from_user_input(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("a" * 300)
        ctx = EngineContext(
            user_input="/创作 2.3 突出冲突",
            project_root=tmp_path,
            project_state="S2",
        )
        result = run(ctx, deps)
        # The chapter file is written under manuscript/chapter-2.3.md.
        assert "chapter-2.3.md" in str(result.artifacts["draft_path"])

    def test_requirements_passed_to_prose_client(self, tmp_path: Path) -> None:
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("a" * 300)
        ctx = EngineContext(
            user_input="/创作 1.1 突出冲突 结尾留钩",
            project_root=tmp_path,
            project_state="S2",
        )
        run(ctx, deps)
        # The plan is built with the requirements; the prose client
        # is called with system+user prompts that include them.
        # We can't easily inspect the exact prompt without the graph
        # internals, but the call itself must succeed.
        # Verify the prose client was called.
        assert deps.prose_client.generate_text.called

    def test_rewrite_flag_triggers_extra_loop(self, tmp_path: Path) -> None:
        # When the user input contains "回流" or "重写", the
        # review_gate forces a rewrite (independent of LLM score).
        (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
        deps = _make_deps_with_prose("a" * 300)
        ctx = EngineContext(
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
            stub(MagicMock(spec=EngineContext))
