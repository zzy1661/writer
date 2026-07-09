"""Tests for the rewritten ``review_chapter`` workflow (PR3).

Added 2026-07-09 (real-writing-pipeline PR3) — covers the 5-node
reviewer graph, decision gate mapping (pass / tweak / needs_rewrite),
continuity findings referencing foreshadow IDs, and report
persistence to ``manuscript/reviews/``.
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
from writer.llm.prose import DeterministicProseClient
from writer.workflows.review_chapter import (
    build_reviewer_graph,
    run,
)
from writer.workflows.types import (
    ConcernVerdict,
    MultiConcernReview,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _RecordingChatModel(BaseChatModel):
    """Fake ``BaseChatModel`` returning a canned MultiConcernReview JSON."""

    last_messages: list = []  # type: ignore[type-arg]
    response_factory: Any = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "recording-fake-reviewer"

    def _generate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        self.last_messages = list(messages)
        response = (
            self.response_factory()
            if self.response_factory
            else AIMessage(content="{}")
        )
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _build_fake_multi_concern(
    *,
    continuity_score: int = 8,
    pacing_score: int = 8,
    prose_score: int = 8,
    continuity_pass: bool = True,
    pacing_pass: bool = True,
    prose_pass: bool = True,
    continuity_findings: list[str] | None = None,
    total: int | None = None,
    summary: str = "all good",
) -> AIMessage:
    """Build a fake ``AIMessage`` carrying MultiConcernReview JSON."""
    payload = {
        "continuity": {
            "score": continuity_score,
            "pass": continuity_pass,
            "findings": continuity_findings or [],
        },
        "pacing": {
            "score": pacing_score,
            "pass": pacing_pass,
            "findings": [],
        },
        "prose": {
            "score": prose_score,
            "pass": prose_pass,
            "findings": [],
        },
        "total_score": total if total is not None else min(
            continuity_score, pacing_score, prose_score
        ),
        "summary": summary,
    }
    return AIMessage(content=json.dumps(payload, ensure_ascii=False))


def _make_deps(
    project_root: Path, *, review_llm: BaseChatModel | None = None
) -> EngineDeps:
    """Build an EngineDeps with the test project root and recording review LLM."""
    deps = production_deps(project_root=project_root)
    deps.prose_client = DeterministicProseClient()
    if review_llm is not None:
        deps.review_llm = review_llm
    return deps


def _write_chapter(project_root: Path, chapter_id: str, content: str) -> Path:
    """Helper: write a chapter file under manuscript/."""
    manuscript_dir = project_root / "manuscript"
    manuscript_dir.mkdir(parents=True, exist_ok=True)
    path = manuscript_dir / f"chapter-{chapter_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """A minimal writer project root."""
    (tmp_path / "AGENT.md").write_text("# test\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: graph topology
# ---------------------------------------------------------------------------


class TestGraphTopology:
    def test_graph_compiles(self) -> None:
        graph = build_reviewer_graph()
        assert graph is not None

    def test_graph_has_five_nodes(self) -> None:
        graph = build_reviewer_graph()
        nodes = list(graph.get_graph().nodes.keys())
        for expected in (
            "load_target_chapter",
            "prep_review_context",
            "aggregate_reviews",
            "decision_gate",
            "persist_review_report",
        ):
            assert expected in nodes


# ---------------------------------------------------------------------------
# Tests: target resolution
# ---------------------------------------------------------------------------


class TestLoadTargetChapter:
    def test_load_specific_chapter(self, project_root: Path) -> None:
        _write_chapter(project_root, "1.3", "first chapter content")
        deps = _make_deps(project_root)
        ctx = EngineContext(
            user_input="/审核 1.3", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.status == "completed"
        text = "".join(result.chunks)
        assert "load_target_chapter" in text
        assert "1.3" in text

    def test_load_current_finds_latest(self, project_root: Path) -> None:
        _write_chapter(project_root, "1.1", "first")
        _write_chapter(project_root, "1.2", "second")
        _write_chapter(project_root, "1.3", "third")
        deps = _make_deps(project_root)
        ctx = EngineContext(
            user_input="/审核", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        # The deterministic path always passes; we just need to
        # confirm the latest chapter was loaded.
        text = "".join(result.chunks)
        assert "1.3" in text

    def test_load_missing_chapter_returns_failed(self, project_root: Path) -> None:
        # Create the manuscript/ directory so we get past the
        # ``manuscript_missing`` check; the chapter file itself is
        # what we expect to be flagged as not found.
        (project_root / "manuscript").mkdir()
        deps = _make_deps(project_root)
        ctx = EngineContext(
            user_input="/审核 99.99", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.status == "failed"
        assert result.metrics.get("error") == "chapter_not_found"

    def test_load_without_project_root_returns_failed(self, tmp_path: Path) -> None:
        # No project_root on the deps; the workflow must fail cleanly.
        deps = production_deps()  # project_root=sentinel
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=None, project_state="S0"
        )
        result = run(ctx, deps)
        assert result.status == "failed"
        assert result.metrics.get("error") == "no_project_root"

    def test_load_without_manuscript_dir_returns_failed(self, project_root: Path) -> None:
        deps = _make_deps(project_root)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.status == "failed"
        assert result.metrics.get("error") == "manuscript_missing"


# ---------------------------------------------------------------------------
# Tests: deterministic path
# ---------------------------------------------------------------------------


class TestDeterministicPath:
    def test_deterministic_pass_decision(self, project_root: Path) -> None:
        _write_chapter(project_root, "1.1", "x" * 200)
        deps = _make_deps(project_root)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.status == "completed"
        assert result.metrics.get("decision") == "pass"
        assert result.metrics.get("total_score") == 8

    def test_deterministic_writes_review_report(self, project_root: Path) -> None:
        _write_chapter(project_root, "1.1", "x" * 200)
        deps = _make_deps(project_root)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        # The report file is in artifacts["review_path"].
        assert "review_path" in result.artifacts
        report_path = result.artifacts["review_path"]
        assert report_path.exists()
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["chapter_id"] == "1.1"
        assert payload["decision"] == "pass"
        assert payload["total_score"] == 8
        assert "timestamp" in payload
        assert "concerns" in payload
        # All three concerns present.
        assert set(payload["concerns"]) == {"continuity", "pacing", "prose"}


# ---------------------------------------------------------------------------
# Tests: decision gate
# ---------------------------------------------------------------------------


class TestDecisionGate:
    def test_pass_when_all_high_and_all_pass(
        self, project_root: Path
    ) -> None:
        _write_chapter(project_root, "1.1", "x" * 200)
        llm = _RecordingChatModel()
        llm.response_factory = lambda: _build_fake_multi_concern(
            continuity_score=9,
            pacing_score=9,
            prose_score=9,
            continuity_pass=True,
            pacing_pass=True,
            prose_pass=True,
            total=9,
        )
        deps = _make_deps(project_root, review_llm=llm)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.metrics.get("decision") == "pass"
        assert result.status == "completed"

    def test_tweak_when_medium_score(self, project_root: Path) -> None:
        _write_chapter(project_root, "1.1", "x" * 200)
        llm = _RecordingChatModel()
        llm.response_factory = lambda: _build_fake_multi_concern(
            continuity_score=7,
            pacing_score=7,
            prose_score=7,
            total=7,
        )
        deps = _make_deps(project_root, review_llm=llm)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.metrics.get("decision") == "tweak"
        assert result.status == "completed"

    def test_needs_rewrite_when_low_score(self, project_root: Path) -> None:
        _write_chapter(project_root, "1.1", "x" * 200)
        llm = _RecordingChatModel()
        llm.response_factory = lambda: _build_fake_multi_concern(
            continuity_score=4,
            pacing_score=4,
            prose_score=4,
            total=4,
        )
        deps = _make_deps(project_root, review_llm=llm)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.metrics.get("decision") == "needs_rewrite"
        assert result.status == "pending"

    def test_needs_rewrite_when_any_concern_below_threshold(
        self, project_root: Path
    ) -> None:
        _write_chapter(project_root, "1.1", "x" * 200)
        llm = _RecordingChatModel()
        llm.response_factory = lambda: _build_fake_multi_concern(
            # total is 7 (tweak territory) but prose is 3 (below
            # DECISION_NEEDS_REWRITE_CONCERN=4) — must escalate to
            # needs_rewrite.
            continuity_score=8,
            pacing_score=8,
            prose_score=3,
            prose_pass=False,
            total=7,
        )
        deps = _make_deps(project_root, review_llm=llm)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        assert result.metrics.get("decision") == "needs_rewrite"


# ---------------------------------------------------------------------------
# Tests: continuity findings reference foreshadow IDs
# ---------------------------------------------------------------------------


class TestContinuityFindings:
    def test_continuity_findings_reference_foreshadows(
        self, project_root: Path
    ) -> None:
        # ``prep_review_context`` returns the IDs from
        # ``foreshadow_search``. The deterministic path puts each ID
        # in the continuity findings list so the persisted report
        # contains them.
        from writer.tools import ToolResult

        result = ToolResult(
            output="active foreshadows: F001, F003, F007"
        )
        deps = _make_deps(project_root)
        deps.tool_registry = MagicMock()
        deps.tool_registry.invoke.return_value = result
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        _write_chapter(project_root, "1.1", "x" * 200)
        result_obj = run(ctx, deps)
        report_path = result_obj.artifacts["review_path"]
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        findings_text = " ".join(
            payload["concerns"]["continuity"].get("findings", [])
        )
        # All three IDs are referenced in the report.
        assert "F001" in findings_text
        assert "F003" in findings_text
        assert "F007" in findings_text

    def test_report_includes_active_foreshadows_list(
        self, project_root: Path
    ) -> None:
        from writer.tools import ToolResult

        deps = _make_deps(project_root)
        deps.tool_registry = MagicMock()
        deps.tool_registry.invoke.return_value = ToolResult(
            output="foreshadows: F001, F003"
        )
        _write_chapter(project_root, "1.1", "x" * 200)
        ctx = EngineContext(
            user_input="/审核 1.1", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        payload = json.loads(result.artifacts["review_path"].read_text(encoding="utf-8"))
        assert payload["active_foreshadows"] == ["F001", "F003"]


# ---------------------------------------------------------------------------
# Tests: argument parsing integration
# ---------------------------------------------------------------------------


class TestArgsIntegration:
    def test_target_passed_through(self, project_root: Path) -> None:
        _write_chapter(project_root, "2.4", "x" * 200)
        deps = _make_deps(project_root)
        ctx = EngineContext(
            user_input="/审核 2.4", project_root=project_root, project_state="S2"
        )
        result = run(ctx, deps)
        payload = json.loads(result.artifacts["review_path"].read_text(encoding="utf-8"))
        assert payload["chapter_id"] == "2.4"

    def test_focus_passed_through_to_review_prompt(
        self, project_root: Path
    ) -> None:
        _write_chapter(project_root, "1.1", "x" * 200)
        llm = _RecordingChatModel()
        # Use real LLM path so we can inspect the prompt
        llm.response_factory = lambda: _build_fake_multi_concern()
        deps = _make_deps(project_root, review_llm=llm)
        ctx = EngineContext(
            user_input="/审核 1.1 重点看伏笔",
            project_root=project_root,
            project_state="S2",
        )
        run(ctx, deps)
        # ``invoke_structured_json`` prepends a JSON contract message
        # so the LLM sees [contract, system, human]. The user
        # message (which carries the focus) is at index 2.
        assert len(llm.last_messages) >= 2
        user_msg = llm.last_messages[-1].content
        assert "重点看伏笔" in user_msg


# ---------------------------------------------------------------------------
# Tests: Pydantic models
# ---------------------------------------------------------------------------


class TestPydanticModels:
    def test_concern_verdict_validates_score(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ConcernVerdict(score=11, pass_=True, findings=[])  # type: ignore[arg-type]

    def test_concern_verdict_alias_round_trips(self) -> None:
        cv = ConcernVerdict.model_validate({"score": 7, "pass": True, "findings": ["x"]})
        assert cv.pass_ is True
        assert cv.score == 7
        assert cv.findings == ["x"]

    def test_multi_concern_review_shape(self) -> None:
        cv = ConcernVerdict(score=8, pass_=True, findings=[])
        review = MultiConcernReview(
            continuity=cv, pacing=cv, prose=cv, total_score=8, summary=""
        )
        assert review.total_score == 8
        assert review.continuity.score == 8
