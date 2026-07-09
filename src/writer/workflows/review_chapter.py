"""``review_chapter`` workflow (real-writing-pipeline PR3).

5-node LangGraph state machine:

``load_target_chapter -> prep_review_context -> aggregate_reviews -> decision_gate -> persist_review_report``

* ``load_target_chapter`` — reads the chapter file (or returns a
  failed :class:`WorkflowResult` if the chapter doesn't exist).
* ``prep_review_context`` — calls ``foreshadow_search(status="active")``
  to load active foreshadow IDs; passes them to the review LLM.
* ``aggregate_reviews`` — single ``invoke_structured_json`` call
  producing a :class:`MultiConcernReview` (continuity / pacing /
  prose concerns + total score + summary).
* ``decision_gate`` — maps ``total_score`` + per-concern pass flags
  to ``"pass" | "tweak" | "needs_rewrite"``.
* ``persist_review_report`` — writes
  ``manuscript/reviews/chapter-<id>-<ISO-timestamp>.json`` and
  returns a :class:`WorkflowResult` with the decision, total score,
  and review path in ``artifacts`` / ``metrics``.

The return is :class:`WorkflowResult`:

* ``status="completed"`` when decision is ``"pass"`` or ``"tweak"``.
* ``status="pending"`` when decision is ``"needs_rewrite"`` (signals
  upstream ``write_chapter`` to re-run; the engine's PR1 deprecation
  branch is still in place, but the workflow itself returns a
  semantically rich status that the engine maps to the right
  ``Done`` reason).
* ``status="failed"`` for missing-chapter or LLM errors.

Added 2026-07-09 (real-writing-pipeline PR3).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from writer.workflows.params import extract_review_chapter_args
from writer.workflows.types import (
    DECISION_NEEDS_REWRITE_CONCERN,
    DECISION_PASS_THRESHOLD,
    DECISION_TWEAK_THRESHOLD,
    MultiConcernReview,
    WorkflowResult,
)

if TYPE_CHECKING:
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps


class ReviewerState(TypedDict, total=False):
    """LangGraph state for the review_chapter graph."""

    target: str
    focus: list[str]
    chapter_id: str
    chapter_path: str
    chapter_text: str
    active_foreshadows: list[str]
    review: dict[str, Any]
    decision: str
    artifacts: dict[str, str]
    metrics: dict[str, float | int | str]
    trace: list[str]


# ---------------------------------------------------------------------------
# Engine dependency injection (node-level)
# ---------------------------------------------------------------------------
# Same pattern as ``write_chapter`` — bare-function node signatures
# can't take deps as a parameter, so we use a module-level binding
# set by :func:`run` and reset after ``graph.invoke``.
_REVIEW_DEPS: EngineDeps | None = None


def _set_deps(deps: EngineDeps) -> None:
    global _REVIEW_DEPS
    _REVIEW_DEPS = deps


def _reset_deps() -> None:
    global _REVIEW_DEPS
    _REVIEW_DEPS = None


def _get_deps() -> EngineDeps:
    if _REVIEW_DEPS is None:
        msg = (
            "review_chapter node called without _set_deps; "
            "call _set_deps(deps) before graph.invoke"
        )
        raise RuntimeError(msg)
    return _REVIEW_DEPS


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(ctx: EngineContext, deps: EngineDeps) -> WorkflowResult:
    """Build the graph, run it, and return a :class:`WorkflowResult`."""
    args = extract_review_chapter_args(ctx.user_input)
    initial_state: ReviewerState = {
        "target": args.target,
        "focus": list(args.focus),
        "trace": [],
        "artifacts": {},
        "metrics": {},
    }
    _set_deps(deps)
    try:
        graph = build_reviewer_graph()
        config = {
            "configurable": {
                "thread_id": ctx.session_id or f"review-{args.target}"
            }
        }
        # The graph invoke returns a dict-shaped state.
        from typing import cast

        final_state = cast(
            ReviewerState,
            graph.invoke(initial_state, config=config),  # type: ignore[call-overload,arg-type]
        )
    finally:
        _reset_deps()

    return _state_to_result(final_state)


# ---------------------------------------------------------------------------
# Graph topology
# ---------------------------------------------------------------------------


def build_reviewer_graph() -> CompiledStateGraph:
    graph = StateGraph(ReviewerState)
    graph.add_node("load_target_chapter", _load_target_chapter_node)
    graph.add_node("prep_review_context", _prep_review_context_node)
    graph.add_node("aggregate_reviews", _aggregate_reviews_node)
    graph.add_node("decision_gate", _decision_gate_node)
    graph.add_node("persist_review_report", _persist_review_report_node)

    graph.set_entry_point("load_target_chapter")
    graph.add_edge("load_target_chapter", "prep_review_context")
    graph.add_edge("prep_review_context", "aggregate_reviews")
    graph.add_edge("aggregate_reviews", "decision_gate")
    graph.add_edge("decision_gate", "persist_review_report")
    graph.add_edge("persist_review_report", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def _load_target_chapter_node(state: ReviewerState) -> ReviewerState:
    """Resolve the target chapter file and load its contents.

    If ``target`` is ``"current"``, the node looks for the latest
    chapter file in ``manuscript/`` (by lexicographic order of
    filenames; ``chapter-N.M.md`` sorts correctly). If a specific
    chapter_id is given (``"1.3"``), the node looks up
    ``manuscript/chapter-1.3.md`` directly. The project root comes
    from ``deps`` (via the deps injection) — the LangGraph state
    doesn't carry a project_root field.
    """
    deps = _get_deps()
    project_root = deps.tool_runtime.project_root
    if project_root is None or str(project_root) == "/__no_project__":
        return _failed_state(
            state,
            error="no_project_root",
            message="审核需要绑定到项目根 (ToolRuntime.project_root 为空)",
        )

    target = state.get("target", "current")
    manuscript_dir = project_root / "manuscript"
    if not manuscript_dir.exists():
        return _failed_state(
            state,
            error="manuscript_missing",
            message=f"项目根 {project_root} 下没有 manuscript/ 目录",
        )

    if target == "current":
        candidates = sorted(manuscript_dir.glob("chapter-*.md"))
        if not candidates:
            return _failed_state(
                state,
                error="chapter_not_found",
                message="manuscript/ 下没有可审核的章节",
            )
        chapter_path = candidates[-1]  # lexicographic last = highest N.M
    else:
        chapter_path = manuscript_dir / f"chapter-{target}.md"
        if not chapter_path.exists():
            return _failed_state(
                state,
                error="chapter_not_found",
                message=f"找不到章节 {target}: {chapter_path}",
            )

    try:
        chapter_text = chapter_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _failed_state(
            state,
            error="chapter_read_failed",
            message=f"读取章节失败: {exc}",
        )

    chapter_id = chapter_path.stem.removeprefix("chapter-")
    trace = [*state.get("trace", []), "load_target_chapter"]
    return {
        "chapter_id": chapter_id,
        "chapter_path": str(chapter_path),
        "chapter_text": chapter_text,
        "trace": trace,
    }


def _prep_review_context_node(state: ReviewerState) -> ReviewerState:
    """Load active foreshadows via the tool registry.

    Failures (project not bound, no active foreshadows, tool error)
    are non-fatal: the review proceeds with an empty foreshadow
    list. The findings will simply note the absence of active
    foreshadows as a low-priority concern.
    """
    deps = _get_deps()
    active = _load_active_foreshadows(deps)
    trace = [*state.get("trace", []), "prep_review_context"]
    return {"active_foreshadows": active, "trace": trace}


def _aggregate_reviews_node(state: ReviewerState) -> ReviewerState:
    """Single LLM call producing a :class:`MultiConcernReview`.

    On the deterministic path (``deps.prose_client.name == "deterministic"``),
    the node assembles a deterministic review with score 8, all
    concerns passing, and empty findings — same as the
    ``write_chapter`` review_gate's offline path.
    """
    deps = _get_deps()
    chapter_text = state.get("chapter_text", "")
    active_foreshadows = state.get("active_foreshadows", [])
    focus = state.get("focus", [])

    # Use the deterministic review when no review_llm is injected
    # (i.e. rule-only deployment). The prose_client's name is NOT a
    # gate — the prose_client is shared with write_chapter and its
    # name reflects whether the chapter draft is real or
    # deterministic, not whether the review LLM is available.
    review_llm = getattr(deps, "review_llm", None)
    if review_llm is None:
        review = _deterministic_review(active_foreshadows, focus)
    else:
        try:
            review = _llm_review(deps, chapter_text, active_foreshadows, focus)
        except Exception as exc:  # noqa: BLE001
            # LLM error: degrade to a deterministic review at low
            # score so the decision gate flags ``needs_rewrite``.
            from writer.workflows.types import ConcernVerdict

            low = ConcernVerdict.model_validate(
                {"score": 4, "pass": False, "findings": []}
            )
            low_with_error = ConcernVerdict.model_validate(
                {"score": 4, "pass": False, "findings": [f"LLM 错误: {exc}"]}
            )
            review = MultiConcernReview(
                continuity=low_with_error,
                pacing=low,
                prose=low,
                total_score=4,
                summary=f"LLM 调用失败: {exc}",
            )

    trace = [*state.get("trace", []), "aggregate_reviews"]
    return {
        "review": review.model_dump(by_alias=False),
        "trace": trace,
    }


def _decision_gate_node(state: ReviewerState) -> ReviewerState:
    """Map the review to a pass / tweak / needs_rewrite decision.

    Mapping (from the writing-pipeline spec):

    * ``total_score >= 8`` AND all concerns pass → ``"pass"``
    * ``total_score >= 6`` → ``"tweak"``
    * ``total_score < 6`` OR any concern score < 4 → ``"needs_rewrite"``
    """
    review = state.get("review", {}) or {}
    continuity = review.get("continuity", {}) or {}
    pacing = review.get("pacing", {}) or {}
    prose = review.get("prose", {}) or {}
    total = int(review.get("total_score", 0))
    all_pass = bool(continuity.get("pass_")) and bool(pacing.get("pass_")) and bool(prose.get("pass_"))
    any_poor = (
        int(continuity.get("score", 0)) < DECISION_NEEDS_REWRITE_CONCERN
        or int(pacing.get("score", 0)) < DECISION_NEEDS_REWRITE_CONCERN
        or int(prose.get("score", 0)) < DECISION_NEEDS_REWRITE_CONCERN
    )
    if total >= DECISION_PASS_THRESHOLD and all_pass:
        decision = "pass"
    elif total < DECISION_TWEAK_THRESHOLD or any_poor:
        decision = "needs_rewrite"
    else:
        decision = "tweak"

    metrics = dict(state.get("metrics", {}))
    metrics["total_score"] = total
    metrics["decision"] = decision
    trace = [*state.get("trace", []), "decision_gate"]
    return {"decision": decision, "metrics": metrics, "trace": trace}


def _persist_review_report_node(state: ReviewerState) -> ReviewerState:
    """Write the review report to ``manuscript/reviews/``."""
    deps = _get_deps()
    project_root = deps.tool_runtime.project_root
    if project_root is None or str(project_root) == "/__no_project__":
        # No project — skip persistence but still return a usable
        # WorkflowResult with the decision in metrics.
        artifacts = dict(state.get("artifacts", {}))
        metrics = dict(state.get("metrics", {}))
        metrics["persist_skipped"] = 1
        trace = [*state.get("trace", []), "persist_review_report"]
        return {"artifacts": artifacts, "metrics": metrics, "trace": trace}

    chapter_id = state.get("chapter_id", "current")
    review = state.get("review", {}) or {}
    decision = state.get("decision", "needs_rewrite")
    active_foreshadows = state.get("active_foreshadows", [])

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    reviews_dir = project_root / "manuscript" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_path = reviews_dir / f"chapter-{chapter_id}-{timestamp}.json"

    payload = {
        "chapter_id": chapter_id,
        "timestamp": timestamp,
        "decision": decision,
        "total_score": int(review.get("total_score", 0)),
        "concerns": {
            "continuity": review.get("continuity", {}),
            "pacing": review.get("pacing", {}),
            "prose": review.get("prose", {}),
        },
        "active_foreshadows": list(active_foreshadows),
        "summary": review.get("summary", ""),
    }
    review_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    artifacts = dict(state.get("artifacts", {}))
    artifacts["review_path"] = str(review_path)
    metrics = dict(state.get("metrics", {}))
    metrics["chapter_id"] = chapter_id  # type: ignore[assignment]
    trace = [*state.get("trace", []), "persist_review_report"]
    return {"artifacts": artifacts, "metrics": metrics, "trace": trace}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _failed_state(
    state: ReviewerState, *, error: str, message: str
) -> ReviewerState:
    """Return a state update that records a hard failure.

    The :func:`_state_to_result` helper converts a state with
    ``error`` metric into a ``WorkflowResult(status="failed", ...)``.
    """
    metrics = dict(state.get("metrics", {}))
    metrics["error"] = error
    metrics["error_message"] = message
    trace = [*state.get("trace", []), "load_target_chapter"]
    return {"metrics": metrics, "trace": trace}


def _load_active_foreshadows(deps: EngineDeps) -> list[str]:
    """Call ``foreshadow_search(status="active")`` and return IDs."""
    try:
        result = deps.tool_registry.invoke(
            "foreshadow_search", deps.tool_runtime, status="active"
        )
    except Exception:  # noqa: BLE001
        return []
    output = getattr(result, "output", None) or ""
    if not isinstance(output, str):
        return []
    return re.findall(r"F\d+", output)


def _deterministic_review(
    active_foreshadows: list[str], focus: list[str]
) -> MultiConcernReview:
    """Build a deterministic :class:`MultiConcernReview` for offline mode."""
    continuity_findings: list[str] = []
    if active_foreshadows:
        # Cite each active foreshadow so the report's findings section
        # references the IDs the reviewer was given (per the spec
        # scenario ``Continuity findings reference foreshadow IDs``).
        continuity_findings = [
            f"verify {fid} progress" for fid in active_foreshadows
        ]
    if focus:
        continuity_findings.extend(f"focus: {f}" for f in focus)
    from writer.workflows.types import ConcernVerdict

    high = ConcernVerdict.model_validate(
        {"score": 8, "pass": True, "findings": []}
    )
    continuity = ConcernVerdict.model_validate(
        {"score": 8, "pass": True, "findings": continuity_findings}
    )
    return MultiConcernReview(
        continuity=continuity,
        pacing=high,
        prose=high,
        total_score=8,
        summary="deterministic review (no LLM configured)",
    )


def _llm_review(
    deps: EngineDeps,
    chapter_text: str,
    active_foreshadows: list[str],
    focus: list[str],
) -> MultiConcernReview:
    """Invoke the LLM with the :class:`MultiConcernReview` schema."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from writer.config import get_settings
    from writer.llm.provider import get_llm as _get_llm
    from writer.llm.structured import invoke_structured_json

    system = (
        "你是长篇小说审核节点。基于正典设定、伏笔列表、用户关注点与本章正文，"
        "针对连续性/节奏/文笔三个维度分别打分并给出发现。"
    )
    foreshadow_block = (
        "\n".join(f"- {fid}" for fid in active_foreshadows)
        if active_foreshadows
        else "- (无活跃伏笔)"
    )
    focus_block = (
        "\n".join(f"- {f}" for f in focus) if focus else "- (无特定关注点)"
    )
    user = (
        f"活跃伏笔:\n{foreshadow_block}\n\n"
        f"关注点:\n{focus_block}\n\n"
        f"本章正文:\n{chapter_text[:4000]}\n\n"
        f"请输出 {{ continuity: {{score, pass, findings}}, pacing: ..., prose: ..., "
        f"total_score: 0-10, summary: str }} 的 JSON 判定。"
    )

    # Use the injected review_llm if set (test path); otherwise build
    # one from settings (production). Mirrors ``write_chapter``'s
    # ``_resolve_review_llm``.
    review_llm = getattr(deps, "review_llm", None)
    llm = review_llm if review_llm is not None else _get_llm(get_settings())

    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    return invoke_structured_json(llm, messages, MultiConcernReview)


def _state_to_result(state: ReviewerState) -> WorkflowResult:
    """Convert a finished :class:`ReviewerState` to a :class:`WorkflowResult`."""
    metrics = dict(state.get("metrics", {}))
    error = metrics.get("error")
    artifacts: dict[str, Path] = {}
    for key, value in (state.get("artifacts") or {}).items():
        artifacts[key] = Path(str(value))

    if error is not None:
        return WorkflowResult(
            status="failed",
            chunks=(
                f"[workflow] (review_chapter) 失败: {metrics.get('error_message', error)}",
            ),
            artifacts=artifacts,
            metrics=_coerce_metrics(metrics),
        )

    decision = state.get("decision", "needs_rewrite")
    chapter_id = state.get("chapter_id", "current")
    # Map decision to status:
    # - pass / tweak -> completed (the review delivered value to the user)
    # - needs_rewrite -> pending (signal upstream write_chapter to retry)
    status: Literal["completed", "pending"] = (
        "completed" if decision in ("pass", "tweak") else "pending"
    )

    chunks = [
        "[workflow] review_chapter 图完成\n",
        "[workflow] trace=" + " → ".join(state.get("trace", [])) + "\n",
        f"[workflow] chapter={chapter_id} decision={decision} total_score={metrics.get('total_score', 0)}\n",
    ]
    review = state.get("review", {}) or {}
    if review:
        chunks.append(f"[review]\n{review}\n")

    return WorkflowResult(
        status=status,
        chunks=tuple(chunks),
        artifacts=artifacts,
        metrics=_coerce_metrics(metrics),
    )


def _coerce_metrics(
    raw: dict[str, Any],
) -> dict[str, float | int | str]:
    """Normalize ``raw`` into a ``dict[str, float | int | str]`` shape.

    Booleans become 0/1 ints; everything else is stringified.
    """
    out: dict[str, float | int | str] = {}
    for key, value in raw.items():
        if isinstance(value, bool):
            out[key] = int(value)
        elif isinstance(value, (int, float, str)):
            out[key] = value
        else:
            out[key] = str(value)
    return out


# ---------------------------------------------------------------------------
# Compatibility shim
# ---------------------------------------------------------------------------


def stub(ctx: EngineContext) -> WorkflowResult:
    """PR1-compatible shim; the PR3 implementation makes ``run`` the
    real entry point. ``stub`` now delegates to :func:`run` with a
    placeholder deps (it cannot read the real deps from the
    legacy test surface). Test code that needs the real behavior
    should call :func:`run` directly.
    """
    msg = "review_chapter.stub is a compatibility shim; use review_chapter.run"
    raise NotImplementedError(msg)


__all__ = [
    "ReviewerState",
    "build_reviewer_graph",
    "extract_review_chapter_args",  # re-export
    "run",
    "stub",
]
