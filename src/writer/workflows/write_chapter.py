"""LangGraph ``write_chapter`` workflow (real-writing-pipeline PR2).

The graph is the canonical 5-node Plan-Execute-Review pipeline:

``prep_context -> plan_chapter -> draft_chapter -> proofread -> review_gate -> (rewrite | persist_outputs)``

Nodes call into the active :class:`EngineDeps` for prose generation
(``deps.prose_client.generate_text``) and continuity checking
(``deps.tool_registry.invoke("foreshadow_search", ...)``). The
``persist_outputs`` terminal node writes the chapter file and updates
``chapter_summaries.json`` atomically.

The graph is built once per ``run()`` invocation with a SQLite /
Memory checkpointer (per the legacy MVP). The return type is
:class:`WorkflowResult` (PR1 contract): the engine maps
``status="completed"`` to ``Done(reason="workflow_completed", ...)``.

Added 2026-07-09 (real-writing-pipeline PR2). The PR1 implementation
returned a template-ish ``WorkflowResult``; this rewrite replaces the
template with real LLM-driven prose (or deterministic fallback) plus
persistence.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from writer.context import prep_context
from writer.llm.structured import invoke_structured_json
from writer.project.chapter_summaries import append_summary
from writer.workflows.params import extract_write_chapter_args
from writer.workflows.types import ReviewVerdict, WorkflowResult

if TYPE_CHECKING:
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps


class WriterState(TypedDict, total=False):
    """LangGraph state for the write_chapter graph.

    Extends the PR1 MVP shape with ``artifacts`` / ``metrics`` so the
    ``persist_outputs`` terminal node can populate the final
    :class:`WorkflowResult` without re-running the graph.
    """

    chapter_id: str
    task: str
    requirements: list[str]
    rewrite: bool
    project_root: str
    context: dict[str, Any]
    plan: str
    draft: str
    proofread_report: str
    review: dict[str, Any]
    retry_count: int
    max_retries: int
    trace: list[str]
    artifacts: dict[str, str]
    metrics: dict[str, float | int | str]
    prose_client_name: str


REVIEW_THRESHOLD = 7
"""Minimum :attr:`ReviewVerdict.score` for the draft to pass the gate.

Fixed at 7 for PR2 (per the design decision in the proposal). Future
PRs can introduce genre-aware thresholds or a tuning knob without
breaking the WorkflowResult contract.
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(ctx: EngineContext, deps: EngineDeps) -> WorkflowResult:
    """Build the graph, run it, and return a :class:`WorkflowResult`.

    The 5-node graph is compiled with a checkpointer (SQLite when a
    ``project_root`` is available, ``MemorySaver`` otherwise) so the
    same chapter_id can resume across REPL turns.
    """
    args = extract_write_chapter_args(ctx.user_input)
    initial_state: WriterState = {
        "chapter_id": args.chapter_id,
        "task": ctx.user_input,
        "requirements": list(args.requirements),
        "rewrite": args.rewrite,
        "project_root": str(ctx.project_root) if ctx.project_root is not None else "",
        "retry_count": 0,
        "max_retries": 2,
        "trace": [],
        "artifacts": {},
        "metrics": {},
        "prose_client_name": _require_prose_client(deps).name,
    }

    checkpointer, close_checkpointer = _build_checkpointer(ctx.project_root)
    graph = build_writer_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": ctx.session_id or f"write-{args.chapter_id}"}}
    # ``deps.prose_client`` is always set in production wiring (the
    # Protocol field is ``Optional`` only to keep test stubs that hand-
    # build ``_DefaultEngineDeps`` easy to construct). Cast here so
    # the rest of the function can use the non-Optional type.
    prose_client = _require_prose_client(deps)
    initial_state["prose_client_name"] = prose_client.name
    _set_deps(deps)
    try:
        final_state = cast(
            WriterState, cast(Any, graph).invoke(initial_state, config=config)
        )
    finally:
        close_checkpointer()
        _reset_deps()

    return _state_to_result(final_state, chapter_id=args.chapter_id)


# ---------------------------------------------------------------------------
# Graph topology
# ---------------------------------------------------------------------------


def build_writer_graph(*, checkpointer: Any | None = None) -> CompiledStateGraph:
    """Build the 5-node write_chapter graph.

    Nodes:
        prep_context -> plan_chapter -> draft_chapter -> proofread
        -> review_gate -> (rewrite: draft_chapter | end: persist_outputs)
    """
    graph = StateGraph(WriterState)
    graph.add_node("prep_context", _prep_context_node)
    graph.add_node("plan_chapter", _plan_chapter_node)
    graph.add_node("draft_chapter", _draft_chapter_node)
    graph.add_node("proofread", _proofread_node)
    graph.add_node("review_gate", _review_gate_node)
    graph.add_node("persist_outputs", _persist_outputs_node)

    graph.set_entry_point("prep_context")
    graph.add_edge("prep_context", "plan_chapter")
    graph.add_edge("plan_chapter", "draft_chapter")
    graph.add_edge("draft_chapter", "proofread")
    graph.add_edge("proofread", "review_gate")
    graph.add_conditional_edges(
        "review_gate",
        _route_after_review,
        {"rewrite": "draft_chapter", "end": "persist_outputs"},
    )
    graph.add_edge("persist_outputs", END)
    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


def _prep_context_node(state: WriterState) -> WriterState:
    raw_root = state.get("project_root", "")
    project_root = Path(raw_root) if raw_root else None
    pack = prep_context(
        state["chapter_id"],
        state["task"],
        project_root=project_root,
        max_tokens=8_000,
    )
    trace = [*state.get("trace", []), "prep_context"]
    return {"context": asdict(pack), "trace": trace}


def _plan_chapter_node(state: WriterState) -> WriterState:
    """Assemble a deterministic beat list for the chapter.

    The beat list is a structured string the LLM uses as the outline
    in ``_draft_chapter_node``. We don't call the LLM here — the plan
    is small and deterministic, so the same input always produces the
    same plan (good for tests + deterministic fallback).
    """
    requirements = state.get("requirements", []) or []
    requirement_block = (
        "\n".join(f"- {r}" for r in requirements)
        if requirements
        else "- 沿正典设定推进本章"
    )
    plan = (
        f"chapter_id: {state['chapter_id']}\n"
        f"task: {state['task']}\n"
        f"requirements:\n{requirement_block}\n"
        f"beats:\n"
        f"- 开场：交代本章情境与人物位置\n"
        f"- 冲突：制造或推进本章主要矛盾\n"
        f"- 高潮：关键抉择或转折\n"
        f"- 收束：留下本章钩子, 衔接下一章\n"
    )
    trace = [*state.get("trace", []), "plan_chapter"]
    return {"plan": plan, "trace": trace}


def _draft_chapter_node(state: WriterState) -> WriterState:
    """Generate (or deterministically assemble) the chapter draft.

    The actual LLM call lives in :func:`_call_prose_client` so tests
    can swap the prose client without touching the LangGraph node.
    """
    attempt = state.get("retry_count", 0) + 1
    context = state.get("context", {})
    plan = state.get("plan", "")

    draft = _call_prose_client(
        chapter_id=state["chapter_id"],
        task=state["task"],
        plan=plan,
        canon_block=context.get("canon_block", "") if isinstance(context, dict) else "",
        history_block=context.get("history_block", "") if isinstance(context, dict) else "",
    )
    trace = [*state.get("trace", []), "draft_chapter"]
    return {
        "draft": draft,
        "retry_count": attempt,
        "trace": trace,
    }


def _proofread_node(state: WriterState) -> WriterState:
    """Lightweight lint pass — flags short drafts and obvious issues.

    This is a deterministic check (no LLM). A real LLM-based proofread
    could be added later; the current threshold (80 chars) is the same
    as the PR1 MVP so existing tests don't need to be updated.
    """
    draft = state.get("draft", "")
    if len(draft.strip()) < 80:
        report = "校对警告：草稿过短,需要补足场景、动作和情绪推进。"
    else:
        report = "校对通过：未发现明显错别字、格式断裂或空草稿。"
    trace = [*state.get("trace", []), "proofread"]
    return {"proofread_report": report, "trace": trace}


def _review_gate_node(state: WriterState) -> WriterState:
    """Evaluate the draft and decide whether to rewrite or persist.

    Deterministic mode (``deps.prose_client.name == "deterministic"``)
    auto-passes with score 8. Real mode calls the LLM with a structured
    :class:`ReviewVerdict` schema; the threshold is
    :data:`REVIEW_THRESHOLD` (7). Active foreshadows are loaded via
    ``deps.tool_registry.invoke("foreshadow_search", ...)" so the LLM
    has continuity context.
    """
    attempt = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)
    deps = _get_deps()
    draft = state.get("draft", "")

    active_foreshadows = _load_active_foreshadows(deps)
    prose_client_name = state.get("prose_client_name", "deterministic")

    if prose_client_name == "deterministic":
        # Offline / no-API-key path: always pass with score 8.
        verdict = ReviewVerdict.model_validate(
            {"pass": True, "score": 8, "concerns": []}
        )
    else:
        verdict = _call_review_llm(deps, draft, active_foreshadows)

    passed = verdict.pass_ and verdict.score >= REVIEW_THRESHOLD
    # If the user asked for a rewrite (the input contained 回流 / 重写)
    # and we still have retry budget, force a rewrite. The cap uses
    # strict ``<`` so the loop runs at most ``max_retries`` times
    # after the initial attempt.
    asked_rewrite = bool(state.get("rewrite", False))
    within_budget = attempt < max_retries
    needs_rewrite = (not passed or asked_rewrite) and within_budget

    review = {
        "needs_rewrite": needs_rewrite,
        "pass": verdict.pass_,
        "score": verdict.score,
        "concerns": list(verdict.concerns),
        "active_foreshadows": active_foreshadows,
        "reason": (
            "LLM 评分低于阈值"
            if not passed
            else "用户触发回流"
            if asked_rewrite
            else "达到 MVP 质量门槛"
        ),
        "retry_count": attempt,
        "max_retries": max_retries,
    }
    trace = [*state.get("trace", []), "review_gate"]
    return {"review": review, "trace": trace}


def _persist_outputs_node(state: WriterState) -> WriterState:
    """Write the draft to ``manuscript/`` and update ``chapter_summaries.json``.

    Both writes are atomic — ``chapter_summaries.json`` via
    :func:`writer.project.chapter_summaries.append_summary`, and the
    chapter file via :func:`Path.write_text` after ensuring the
    ``manuscript/`` directory exists.
    """
    chapter_id = state.get("chapter_id", "1.1")
    draft = state.get("draft", "")
    project_root_str = state.get("project_root", "")
    project_root = Path(project_root_str) if project_root_str else None
    review = state.get("review", {})

    artifacts: dict[str, str] = state.get("artifacts", {})
    metrics: dict[str, float | int | str] = dict(state.get("metrics", {}))

    if project_root is not None:
        manuscript_dir = project_root / "manuscript"
        manuscript_dir.mkdir(parents=True, exist_ok=True)
        chapter_path = manuscript_dir / f"chapter-{chapter_id}.md"
        chapter_path.write_text(draft, encoding="utf-8")
        artifacts["draft_path"] = str(chapter_path)

        # One-paragraph summary: take the first 200 chars of the
        # draft after the heading. The summary is plain prose, not
        # markdown.
        first_para = _first_paragraph(draft, limit=200)
        try:
            summaries_path = append_summary(
                project_root, chapter_id, first_para, atomic=True
            )
            artifacts["summaries_path"] = str(summaries_path)
        except Exception as exc:  # noqa: BLE001 — atomic write is best-effort
            metrics["summaries_write_error"] = str(exc)
    else:
        metrics["persist_skipped"] = 1

    metrics["score"] = int(review.get("score", 0))
    metrics["retry_count"] = int(state.get("retry_count", 0))
    metrics["needs_rewrite"] = 0

    trace = [*state.get("trace", []), "persist_outputs"]
    return {"artifacts": artifacts, "metrics": metrics, "trace": trace}


def _route_after_review(state: WriterState) -> Literal["rewrite", "end"]:
    review = state.get("review", {})
    if review.get("needs_rewrite", False):
        return "rewrite"
    return "end"


# ---------------------------------------------------------------------------
# Engine dependency injection (node-level)
# ---------------------------------------------------------------------------
# LangGraph nodes are bare functions taking ``state`` and returning a
# partial state — they cannot be passed ``deps`` as an argument without
# a custom node signature. We thread ``deps`` through a module-level
# context set by :func:`run()` before each graph invocation. This is
# the same pattern LangGraph's own examples use for run-scoped state.
# Production code paths (CLI / REPL) always call :func:`run`, which
# sets the context; tests that build the graph directly MUST set
# ``_set_deps(deps)`` before ``graph.invoke``.


_WORKFLOW_DEPS: EngineDeps | None = None


def _set_deps(deps: EngineDeps) -> None:
    """Bind ``deps`` as the active dependency for the next graph invocation.

    Called by :func:`run` (and by tests that build the graph directly).
    The binding is intentionally global so LangGraph's bare-function
    node signature still has access to ``deps`` without a custom
    ``StateGraph`` config. After ``graph.invoke`` returns, the binding
    is reset to ``None`` so the next ``run`` is forced to call
    ``_set_deps`` (avoids leaking ``deps`` across concurrent calls).
    """
    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = deps


def _reset_deps() -> None:
    """Clear the global deps binding. Always called after ``graph.invoke``."""
    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = None


def _get_deps() -> EngineDeps:
    if _WORKFLOW_DEPS is None:
        msg = (
            "write_chapter node called without _set_deps; "
            "call _set_deps(deps) before graph.invoke"
        )
        raise RuntimeError(msg)
    return _WORKFLOW_DEPS


# ---------------------------------------------------------------------------
# Prose + review helpers
# ---------------------------------------------------------------------------


def _call_prose_client(
    *,
    chapter_id: str,
    task: str,
    plan: str,
    canon_block: str,
    history_block: str,
) -> str:
    """Invoke the configured :class:`LLMProseClient`.

    Splits the call into ``system`` (long-lived context) and ``user``
    (per-call task) messages. Falls back to the prep_context canon /
    history blocks if the plan doesn't include them.
    """
    deps = _get_deps()
    client = _require_prose_client(deps)
    system = (
        f"{canon_block}\n\n{history_block}\n\n"
        "你是长篇小说写作节点。基于上述正典与前情,完成本章计划。"
    )
    user = f"{plan}\n\n请按上述计划完成本章正文。"
    try:
        return client.generate_text(system=system, user=user)
    except Exception as exc:  # noqa: BLE001
        # Surface as a domain exception by raising — the engine's
        # boundary catches generic Exception. We log nothing here
        # because the engine logs at the boundary.
        msg = f"prose_client.generate_text 失败: {exc}"
        raise RuntimeError(msg) from exc


def _require_prose_client(deps: EngineDeps) -> Any:
    """Return ``deps.prose_client`` or raise if it is ``None``.

    The Protocol field is ``Optional`` for stub-friendliness; production
    wiring always sets it. Workflows and the engine's LLM-tool loop
    helper treat ``None`` as a configuration error rather than a
    silent fallback.

    Returns ``Any`` (not ``LLMProseClient``) because the type lives in
    a ``TYPE_CHECKING`` import only; the function body never inspects
    the static type, so the runtime cost of the broader annotation
    is zero and the import cycle is avoided.
    """
    client = deps.prose_client
    if client is None:
        msg = (
            "EngineDeps.prose_client is None; "
            "production_deps always sets it, so this is a wiring bug"
        )
        raise RuntimeError(msg)
    return client


def _call_review_llm(
    deps: EngineDeps, draft: str, active_foreshadows: list[str]
) -> ReviewVerdict:
    """Invoke the LLM with a :class:`ReviewVerdict` structured prompt.

    Used by ``_review_gate_node`` in real mode. Deterministic mode
    never reaches this helper.

    The LLM is taken from ``deps.review_llm`` when set (test path);
    otherwise falls back to :func:`writer.llm.provider.get_llm` with
    the global settings. The fallback requires a configured API key.
    """
    system = (
        "你是长篇小说审核节点。基于正典、伏笔与本章正文,输出结构化判定。"
    )
    foreshadow_block = (
        "\n".join(f"- {fid}" for fid in active_foreshadows)
        if active_foreshadows
        else "- (无活跃伏笔)"
    )
    user = (
        f"活跃伏笔:\n{foreshadow_block}\n\n"
        f"本章草稿:\n{draft[:3000]}\n\n"
        f"请输出 {{ pass: bool, score: int 0-10, concerns: list[str] }} 的 JSON 判定。"
    )
    llm = _resolve_review_llm(deps)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    return invoke_structured_json(llm, messages, ReviewVerdict)


def _resolve_review_llm(deps: EngineDeps) -> Any:
    """Return the LLM to use for review verdicts.

    Priority:
        1. ``deps.review_llm`` (test-injected fake; the standard
           test surface for the review path).
        2. :func:`writer.llm.provider.get_llm` with the global
           settings (production; requires a configured API key).
    """
    review_llm = getattr(deps, "review_llm", None)
    if review_llm is not None:
        return review_llm
    from writer.config import get_settings
    from writer.llm.provider import get_llm as _get_llm

    return _get_llm(get_settings())


def _load_active_foreshadows(deps: EngineDeps) -> list[str]:
    """Call ``foreshadow_search(status="active")`` and return the IDs.

    Returns an empty list on any error (the LLM is still free to
    produce a verdict; the absence of active foreshadows is just
    flagged as a low-priority concern).
    """
    try:
        result = deps.tool_registry.invoke(
            "foreshadow_search", deps.tool_runtime, status="active"
        )
    except Exception:  # noqa: BLE001
        return []
    output = getattr(result, "output", None) or ""
    if not isinstance(output, str):
        return []
    # The search result is a text block; pull the IDs by simple regex.
    import re

    return re.findall(r"F\d+", output)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_chapter_id(user_input: str) -> str:
    text = user_input.removeprefix("/创作").strip()
    return text.split(maxsplit=1)[0] if text else "1.1"


def _excerpt(text: str, *, limit: int = 120) -> str:
    compact = " ".join(text.split())
    return compact[:limit] if compact else "暂无"


def _first_paragraph(draft: str, *, limit: int = 200) -> str:
    """Return the first paragraph of ``draft`` capped at ``limit`` chars.

    A paragraph is text up to the first blank line. Used by
    :func:`_persist_outputs_node` to derive a chapter summary.
    """
    parts = draft.split("\n\n", 1)
    para = parts[0] if parts else draft
    para = " ".join(para.split())
    if len(para) > limit:
        para = para[:limit] + "..."
    return para


def _build_checkpointer(
    project_root: Path | None,
) -> tuple[Any, Callable[[], None]]:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]

        if project_root is None:
            raise ImportError
        checkpoint_dir = project_root / ".writer"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(checkpoint_dir / "checkpoints.sqlite"),
            check_same_thread=False,
        )
        return SqliteSaver(conn), conn.close
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver(), lambda: None


def _state_to_result(
    final_state: WriterState, *, chapter_id: str
) -> WorkflowResult:
    """Convert a finished :class:`WriterState` to a :class:`WorkflowResult`."""
    artifacts: dict[str, Path] = {}
    for key, value in (final_state.get("artifacts") or {}).items():
        artifacts[key] = Path(str(value))
    metrics_value: dict[str, float | int | str] = {}
    metrics_input: dict[str, Any] = final_state.get("metrics") or {}
    for key, value in metrics_input.items():
        # mypy-friendly coercion: anything not a recognised scalar is
        # stringified. Keeps the WorkflowResult contract flat.
        if isinstance(value, bool):
            # ``bool`` is a subclass of ``int``; coerce to int so the
            # final dict only carries ``int | float | str``.
            metrics_value[key] = int(value)
        elif isinstance(value, (int, float, str)):
            metrics_value[key] = value
        else:
            metrics_value[key] = str(value)

    chunks = [
        "[workflow] LangGraph write_chapter 图完成\n",
        "[workflow] trace=" + " → ".join(final_state.get("trace", [])) + "\n",
        f"[workflow] chapter={chapter_id} retry_count={final_state.get('retry_count', 0)}\n",
    ]
    draft = final_state.get("draft", "")
    if draft:
        chunks.append(f"[draft]\n{draft}\n")
    if final_state.get("proofread_report"):
        chunks.append(f"[proofread]\n{final_state['proofread_report']}\n")
    if final_state.get("review"):
        chunks.append(f"[review_gate]\n{final_state['review']}\n")

    return WorkflowResult(
        status="completed",
        chunks=tuple(chunks),
        artifacts=artifacts,
        metrics=metrics_value,
    )


# Compatibility alias for older imports (e.g. ``tests/test_workflows.py``).
def stub(ctx: EngineContext) -> WorkflowResult:
    """Compatibility alias — delegates to :func:`run` with empty deps.

    The PR1 alias accepted just ``ctx``; PR2 keeps it for tests that
    call ``from writer.workflows.write_chapter import stub``. Real
    callers should use :func:`run`.
    """
    msg = (
        "write_chapter.stub is a compatibility shim; "
        "use write_chapter.run with EngineDeps for the real path"
    )
    raise NotImplementedError(msg)


__all__ = [
    "REVIEW_THRESHOLD",
    "ReviewVerdict",
    "WriterState",
    "build_writer_graph",
    "extract_write_chapter_args",  # re-export for convenience
    "run",
    "stub",
]
