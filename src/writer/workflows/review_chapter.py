"""``review_chapter`` 工作流（real-writing-pipeline PR3）。

5 节点 LangGraph 状态机：

``load_target_chapter -> prep_review_context -> aggregate_reviews -> decision_gate -> persist_review_report``

* ``load_target_chapter`` —— 读取章节文件（若章节不存在则返回
  失败的 :class:`WorkflowResult`）。
* ``prep_review_context`` —— 调用 ``foreshadow_search(status="active")``
  加载活跃伏笔 IDs；把它们传给 review LLM。
* ``aggregate_reviews`` —— 单次 ``invoke_structured_json`` 调用
  产出 :class:`MultiConcernReview`（continuity / pacing / prose
  三个 concern + 总分 + summary）。
* ``decision_gate`` —— 把 ``total_score`` + 每个 concern 的 pass 标志
  映射为 ``"pass" | "tweak" | "needs_rewrite"``。
* ``persist_review_report`` —— 写入
  ``manuscript/reviews/chapter-<id>-<ISO-timestamp>.json`` 并返回
  一个 :class:`WorkflowResult`，将决策、总分和 review 路径放入
  ``artifacts`` / ``metrics``。

返回 :class:`WorkflowResult`：

* ``status="completed"`` —— 决策为 ``"pass"`` 或 ``"tweak"`` 时。
* ``status="pending"`` —— 决策为 ``"needs_rewrite"`` 时（信号上游
  ``write_chapter`` 重跑；引擎的 PR1 弃用分支仍在，但工作流本身
  返回语义丰富的 status，由引擎映射到正确的 ``Done`` reason）。
* ``status="failed"`` —— 章节缺失或 LLM 错误。

2026-07-09 增补（real-writing-pipeline PR3）。
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
    """LangGraph review_chapter 图的状态。"""

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
# 引擎依赖注入（节点级）
# ---------------------------------------------------------------------------
# 与 ``write_chapter`` 同样的模式 —— 裸函数节点签名无法把 deps
# 作为参数，所以使用模块级绑定，由 :func:`run` 设置并在
# ``graph.invoke`` 之后重置。
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
# 公开入口
# ---------------------------------------------------------------------------


def run(ctx: EngineContext, deps: EngineDeps) -> WorkflowResult:
    """构建图，运行它，并返回 :class:`WorkflowResult`。"""
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
        # graph invoke 返回 dict 形态状态。
        from typing import cast

        final_state = cast(
            ReviewerState,
            graph.invoke(initial_state, config=config),  # type: ignore[call-overload,arg-type]
        )
    finally:
        _reset_deps()

    return _state_to_result(final_state)


# ---------------------------------------------------------------------------
# 图拓扑
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
# 节点实现
# ---------------------------------------------------------------------------


def _load_target_chapter_node(state: ReviewerState) -> ReviewerState:
    """解析目标章节文件并加载其内容。

    若 ``target`` 为 ``"current"``，节点按文件名字典序在
    ``manuscript/`` 中查找最新章节（``chapter-N.M.md`` 排序正确）。
    若给出具体 chapter_id（``"1.3"``），节点直接查找
    ``manuscript/chapter-1.3.md``。项目根目录来自 ``deps``（通过 deps
    注入）—— LangGraph state 不携带 project_root 字段。
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
        chapter_path = candidates[-1]  # 字典序末位 = 最高 N.M
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
    """通过 tool registry 加载活跃伏笔。

    失败（项目未绑定、无活跃伏笔、工具错误）非致命：review 用
    空伏笔列表继续。发现将仅把缺少活跃伏笔作为低优先级关注点。
    """
    deps = _get_deps()
    active = _load_active_foreshadows(deps)
    trace = [*state.get("trace", []), "prep_review_context"]
    return {"active_foreshadows": active, "trace": trace}


def _aggregate_reviews_node(state: ReviewerState) -> ReviewerState:
    """单次 LLM 调用产出 :class:`MultiConcernReview`。

    确定性路径（``deps.prose_client.name == "deterministic"``）下，
    节点用 score 8、所有 concern 通过、findings 为空组装一个
    确定性的 review —— 与 ``write_chapter`` review_gate 的离线路径相同。
    """
    deps = _get_deps()
    chapter_text = state.get("chapter_text", "")
    active_foreshadows = state.get("active_foreshadows", [])
    focus = state.get("focus", [])

    # 当未注入 review_llm（即纯规则部署）时使用确定性 review。
    # prose_client 的 name 不是 gate —— prose_client 与 write_chapter
    # 共享，其 name 反映章节草稿是真实还是确定性，而非 review LLM
    # 是否可用。
    review_llm = getattr(deps, "review_llm", None)
    if review_llm is None:
        review = _deterministic_review(active_foreshadows, focus)
    else:
        try:
            review = _llm_review(deps, chapter_text, active_foreshadows, focus)
        except Exception as exc:  # noqa: BLE001
            # LLM 错误：以低分降级到确定性 review，让 decision_gate
            # 标记 ``needs_rewrite``。
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
    """把 review 映射为 pass / tweak / needs_rewrite 决策。

    映射（来自 writing-pipeline spec）：

    * ``total_score >= 8`` AND 所有 concern 通过 → ``"pass"``
    * ``total_score >= 6`` → ``"tweak"``
    * ``total_score < 6`` OR 任一 concern score < 4 → ``"needs_rewrite"``
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
    """把 review 报告写入 ``manuscript/reviews/``。"""
    deps = _get_deps()
    project_root = deps.tool_runtime.project_root
    if project_root is None or str(project_root) == "/__no_project__":
        # 无项目 —— 跳过持久化但仍返回带 metrics 中决策的可用
        # WorkflowResult。
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
# 辅助函数
# ---------------------------------------------------------------------------


def _failed_state(
    state: ReviewerState, *, error: str, message: str
) -> ReviewerState:
    """返回记录硬失败的状态更新。

    :func:`_state_to_result` helper 把带 ``error`` metric 的状态转换
    为 ``WorkflowResult(status="failed", ...)``。
    """
    metrics = dict(state.get("metrics", {}))
    metrics["error"] = error
    metrics["error_message"] = message
    trace = [*state.get("trace", []), "load_target_chapter"]
    return {"metrics": metrics, "trace": trace}


def _load_active_foreshadows(deps: EngineDeps) -> list[str]:
    """调用 ``foreshadow_search(status="active")`` 并返回 IDs。"""
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
    """为离线模式构建确定性的 :class:`MultiConcernReview`。"""
    continuity_findings: list[str] = []
    if active_foreshadows:
        # 引用每个活跃伏笔，让报告的 findings 段落引用 reviewer
        # 被给到的 IDs（per spec 场景 ``Continuity findings reference foreshadow IDs``）。
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
    """用 :class:`MultiConcernReview` schema 调用 LLM。"""
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

    # 若设置了注入的 review_llm 则使用（测试路径）；否则基于
    # settings 构建（生产）。镜像 ``write_chapter`` 的
    # ``_resolve_review_llm``。
    review_llm = getattr(deps, "review_llm", None)
    llm = review_llm if review_llm is not None else _get_llm(get_settings())

    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    return invoke_structured_json(llm, messages, MultiConcernReview)


def _state_to_result(state: ReviewerState) -> WorkflowResult:
    """把已完成的 :class:`ReviewerState` 转为 :class:`WorkflowResult`。"""
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
    # 把决策映射到 status：
    # - pass / tweak -> completed（review 为用户提供了价值）
    # - needs_rewrite -> pending（信号上游 write_chapter 重试）
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
    """把 ``raw`` 规范化为 ``dict[str, float | int | str]`` 形态。

    布尔变为 0/1 int；其他都被字符串化。
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
# 兼容 shim
# ---------------------------------------------------------------------------


def stub(ctx: EngineContext) -> WorkflowResult:
    """PR1 兼容 shim；PR3 实现让 ``run`` 成为真实入口。``stub`` 现在
    委托给 :func:`run` 与占位 deps（它无法从遗留测试表面读取真实 deps）。
    需要真实行为的测试代码应直接调用 :func:`run`。
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
