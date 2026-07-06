"""LangGraph ``write_chapter`` workflow.

The graph is intentionally small but real:

``prep_context -> write_chapter -> proofread -> review_gate -> (rewrite | END)``

Nodes are deterministic for the MVP, which keeps tests offline while proving
the workflow shape, context injection, review gate, and checkpoint plumbing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from writer.context import prep_context

if TYPE_CHECKING:
    from writer.engine.context import EngineContext


class WriterState(TypedDict, total=False):
    chapter_id: str
    task: str
    project_root: str
    context: dict[str, Any]
    draft: str
    proofread_report: str
    review: dict[str, Any]
    retry_count: int
    max_retries: int
    trace: list[str]


def run(ctx: EngineContext) -> list[str]:
    """Run the minimum Plan-Execute-Review graph and return stream chunks."""

    chapter_id = _extract_chapter_id(ctx.user_input)
    initial_state: WriterState = {
        "chapter_id": chapter_id,
        "task": ctx.user_input,
        "project_root": str(ctx.project_root) if ctx.project_root is not None else "",
        "retry_count": 0,
        "max_retries": 2,
        "trace": [],
    }

    checkpointer, close_checkpointer = _build_checkpointer(ctx.project_root)
    graph = build_writer_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": ctx.session_id or f"write-{chapter_id}"}}
    try:
        final_state = cast(WriterState, cast(Any, graph).invoke(initial_state, config=config))
    finally:
        close_checkpointer()

    context = final_state.get("context", {})
    token_audit = context.get("token_audit", {}) if isinstance(context, dict) else {}
    review = final_state.get("review", {})

    return [
        "[workflow] LangGraph write_chapter 图完成\n",
        "[workflow] trace=" + " → ".join(final_state.get("trace", [])) + "\n",
        f"[workflow] chapter={chapter_id} retry_count={final_state.get('retry_count', 0)}\n",
        f"[context] token_audit={token_audit}\n",
        f"[draft]\n{final_state.get('draft', '')}\n",
        f"[proofread]\n{final_state.get('proofread_report', '')}\n",
        f"[review_gate]\n{review}\n",
    ]


def build_writer_graph(*, checkpointer: Any | None = None) -> CompiledStateGraph:
    graph = StateGraph(WriterState)
    graph.add_node("prep_context", _prep_context_node)
    graph.add_node("write_chapter", _write_chapter_node)
    graph.add_node("proofread", _proofread_node)
    graph.add_node("review_gate", _review_gate_node)

    graph.set_entry_point("prep_context")
    graph.add_edge("prep_context", "write_chapter")
    graph.add_edge("write_chapter", "proofread")
    graph.add_edge("proofread", "review_gate")
    graph.add_conditional_edges(
        "review_gate",
        _route_after_review,
        {"rewrite": "write_chapter", "end": END},
    )
    return graph.compile(checkpointer=checkpointer)


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


def _write_chapter_node(state: WriterState) -> WriterState:
    attempt = state.get("retry_count", 0) + 1
    context = state.get("context", {})
    task = state["task"]
    canon = context.get("canon_block", "") if isinstance(context, dict) else ""
    history = context.get("history_block", "") if isinstance(context, dict) else ""
    draft = (
        f"第 {state['chapter_id']} 章草稿（第 {attempt} 稿）\n\n"
        f"任务：{task}\n\n"
        "正文占位：主角沿着既有因果推进本章行动，保留前文伏笔，并在章末制造新的期待。\n\n"
        f"正典参考：{_excerpt(canon)}\n\n"
        f"前情参考：{_excerpt(history)}"
    )
    trace = [*state.get("trace", []), "write_chapter"]
    return {"draft": draft, "retry_count": attempt, "trace": trace}


def _proofread_node(state: WriterState) -> WriterState:
    draft = state.get("draft", "")
    report = "校对通过：未发现明显错别字、格式断裂或空草稿。"
    if len(draft.strip()) < 80:
        report = "校对警告：草稿过短，需要补足场景、动作和情绪推进。"
    trace = [*state.get("trace", []), "proofread"]
    return {"proofread_report": report, "trace": trace}


def _review_gate_node(state: WriterState) -> WriterState:
    task = state["task"]
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)
    asks_rewrite = "回流" in task or "重写" in task
    needs_rewrite = asks_rewrite and retry_count < max_retries
    review = {
        "needs_rewrite": needs_rewrite,
        "reason": "用户任务触发回流测试" if needs_rewrite else "达到 MVP 质量门槛",
        "retry_count": retry_count,
        "max_retries": max_retries,
    }
    trace = [*state.get("trace", []), "review_gate"]
    return {"review": review, "trace": trace}


def _route_after_review(state: WriterState) -> Literal["rewrite", "end"]:
    review = state.get("review", {})
    return "rewrite" if review.get("needs_rewrite") else "end"


def _extract_chapter_id(user_input: str) -> str:
    text = user_input.removeprefix("/写").strip()
    return text.split(maxsplit=1)[0] if text else "1.1"


def _excerpt(text: str, *, limit: int = 120) -> str:
    compact = " ".join(text.split())
    return compact[:limit] if compact else "暂无"


def _build_checkpointer(project_root: Path | None) -> tuple[Any, Callable[[], None]]:
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


def stub(ctx: EngineContext) -> list[str]:
    """Compatibility alias for older tests/imports."""

    return run(ctx)


__all__ = ["WriterState", "build_writer_graph", "run", "stub"]
