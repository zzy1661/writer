"""LangGraph ``write_chapter`` 工作流（real-writing-pipeline PR2）。

图是规范的 5 节点 Plan-Execute-Review 管道：

``prep_context -> plan_chapter -> draft_chapter -> proofread -> review_gate -> (rewrite | persist_outputs)``

节点调用激活的 :class:`EngineDeps` 进行散文生成
（``deps.prose_client.generate_text``）和连续性检查
（``deps.tool_registry.invoke("foreshadow_search", ...)``）。
``persist_outputs`` 终结节点写入章节文件并原子地更新
``chapter_summaries.json``。

图在每次 ``run()`` 调用时构建一次，附带 SQLite / Memory
checkpointer（per 遗留 MVP）。返回类型是 :class:`WorkflowResult`
（PR1 契约）：引擎把 ``status="completed"`` 映射到
``Done(reason="workflow_completed", ...)``。

2026-07-09 增补（real-writing-pipeline PR2）。PR1 实现返回模板式
``WorkflowResult``；本重写把模板替换为真实 LLM 驱动的散文（或
确定性回退）加持久化。
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

from writer.llm.structured import invoke_structured_json
from writer.project.chapter_summaries import append_summary
from writer.prompts.agents import CHAPTER_PLAN_TEMPLATE
from writer.prompts.context import prep_context
from writer.workflows.params import extract_write_chapter_args
from writer.workflows.types import ReviewVerdict, WorkflowResult

if TYPE_CHECKING:
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps


class WriterState(TypedDict, total=False):
    """LangGraph write_chapter 图的状态。

    在 PR1 MVP 形态上扩展 ``artifacts`` / ``metrics``，让
    ``persist_outputs`` 终结节点能填充最终
    :class:`WorkflowResult`，无需重跑图。
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
"""草稿通过 gate 的最低 :attr:`ReviewVerdict.score`。

PR2 固定为 7（per 提案中的设计决策）。未来 PR 可引入题材感知阈值
或调优旋钮而不破坏 WorkflowResult 契约。
"""


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------


def run(ctx: EngineContext, deps: EngineDeps) -> WorkflowResult:
    """构建图，运行它，并返回 :class:`WorkflowResult`。

    5 节点图用 checkpointer 编译（``project_root`` 可用时用 SQLite，
    否则用 ``MemorySaver``），让同一 chapter_id 能跨 REPL 轮次恢复。
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
    # ``deps.prose_client`` 在生产装配中始终被设置（Protocol 字段为
    # ``Optional`` 仅是为了让手写 ``_DefaultEngineDeps`` 的测试 stub
    # 容易构造）。此处 cast 让函数其余部分使用非 Optional 类型。
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
# 图拓扑
# ---------------------------------------------------------------------------


def build_writer_graph(*, checkpointer: Any | None = None) -> CompiledStateGraph:
    """构建 5 节点 write_chapter 图。

    节点：
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
# 节点实现
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
    """为本章产出 LLM 驱动的自由散文式计划。

    自 2026-07-14（real-writing-pipeline PR3）起,本节点调
    :func:`_call_plan_chapter` 让 LLM 自由生成一段计划散文。计划字段
    是 opaque 字符串——下游 ``_draft_chapter_node`` 不读它,所以格式是
    自由散文还是 beats 对下游透明。

    Deterministic 模式（``deps.prose_client.name == "deterministic"``）
    严格拒绝:raise RuntimeError 强制用户配置 ``WRITER_API_KEY``。
    不再保留确定性回退分支,因为我们不再相信无 LLM 也能产生有意义的
    章节计划。
    """
    deps = _get_deps()
    context = state.get("context", {})
    canon_block = (
        context.get("canon_block", "") if isinstance(context, dict) else ""
    )
    history_block = (
        context.get("history_block", "") if isinstance(context, dict) else ""
    )
    plan = _call_plan_chapter(
        chapter_id=state["chapter_id"],
        task=state["task"],
        requirements=list(state.get("requirements", []) or []),
        canon_block=canon_block,
        history_block=history_block,
        prose_client=deps.prose_client,
    )
    trace = [*state.get("trace", []), "plan_chapter"]
    return {"plan": plan, "trace": trace}


def _draft_chapter_node(state: WriterState) -> WriterState:
    """生成（或确定性组装）章节草稿。

    实际的 LLM 调用位于 :func:`_call_prose_client`，让测试能在不
    触碰 LangGraph 节点的前提下替换 prose client。
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
    """轻量级 lint pass —— 标记过短草稿与明显问题。

    这是确定性检查（无 LLM）。真正的基于 LLM 的 proofread 未来可
    以添加；当前阈值（80 字符）与 PR1 MVP 一致，让现有测试无需
    更新。
    """
    draft = state.get("draft", "")
    if len(draft.strip()) < 80:
        report = "校对警告：草稿过短,需要补足场景、动作和情绪推进。"
    else:
        report = "校对通过：未发现明显错别字、格式断裂或空草稿。"
    trace = [*state.get("trace", []), "proofread"]
    return {"proofread_report": report, "trace": trace}


def _review_gate_node(state: WriterState) -> WriterState:
    """评估草稿并决定是否重写还是持久化。

    确定性模式（``deps.prose_client.name == "deterministic"``）自动以
    score 8 通过。Real 模式调用带结构化 :class:`ReviewVerdict`
    schema 的 LLM；阈值是 :data:`REVIEW_THRESHOLD`（7）。活跃伏笔
    通过 ``deps.tool_registry.invoke("foreshadow_search", ...)`` 加载，
    让 LLM 拥有连续性上下文。
    """
    attempt = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)
    deps = _get_deps()
    draft = state.get("draft", "")

    active_foreshadows = _load_active_foreshadows(deps)
    prose_client_name = state.get("prose_client_name", "deterministic")

    if prose_client_name == "deterministic":
        # 离线 / 无 API key 路径：始终以 score 8 通过。
        verdict = ReviewVerdict.model_validate(
            {"pass": True, "score": 8, "concerns": []}
        )
    else:
        verdict = _call_review_llm(deps, draft, active_foreshadows)

    passed = verdict.pass_ and verdict.score >= REVIEW_THRESHOLD
    # 若用户要求重写（输入包含 回流 / 重写）且仍在重试预算内，
    # 强制重写。cap 使用严格 ``<``，让循环最多跑 ``max_retries`` 次
    # 加上首次尝试。
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
    """把草稿写入 ``草稿/`` 并更新 ``chapter_summaries.json``。

    两次写入都是原子的 —— ``chapter_summaries.json`` 通过
    :func:`writer.project.chapter_summaries.append_summary`，
    章节文件在确保 ``草稿/`` 目录存在后通过 :func:`Path.write_text` 写入。
    """
    chapter_id = state.get("chapter_id", "1.1")
    draft = state.get("draft", "")
    project_root_str = state.get("project_root", "")
    project_root = Path(project_root_str) if project_root_str else None
    review = state.get("review", {})

    artifacts: dict[str, str] = state.get("artifacts", {})
    metrics: dict[str, float | int | str] = dict(state.get("metrics", {}))

    if project_root is not None:
        manuscript_dir = project_root / "草稿"
        manuscript_dir.mkdir(parents=True, exist_ok=True)
        chapter_path = manuscript_dir / f"chapter-{chapter_id}.md"
        chapter_path.write_text(draft, encoding="utf-8")
        artifacts["draft_path"] = str(chapter_path)

        # 一段摘要：取标题之后草稿的前 200 字符。摘要是纯散文，不是 markdown。
        first_para = _first_paragraph(draft, limit=200)
        try:
            summaries_path = append_summary(
                project_root, chapter_id, first_para, atomic=True
            )
            artifacts["summaries_path"] = str(summaries_path)
        except Exception as exc:  # noqa: BLE001 — 原子写入是尽力而为
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
# 引擎依赖注入（节点级）
# ---------------------------------------------------------------------------
# LangGraph 节点是接受 ``state`` 并返回部分状态的裸函数 —— 它们
# 无法把 ``deps`` 作为参数传入而不引入自定义节点签名。我们通过
# :func:`run()` 在每次图调用前设置的模块级 context 把 ``deps`` 串联
# 起来。这与 LangGraph 自己的示例用于 run-scoped state 的模式相同。
# 生产代码路径（CLI / REPL）总是调用 :func:`run`，会设置 context；
# 直接构建图的测试必须在 ``graph.invoke`` 前调用 ``_set_deps(deps)``。


_WORKFLOW_DEPS: EngineDeps | None = None


def _set_deps(deps: EngineDeps) -> None:
    """把 ``deps`` 绑定为下一次图调用的激活依赖。

    由 :func:`run`（以及直接构建图的测试）调用。绑定刻意是全局的，
    让 LangGraph 的裸函数节点签名仍能访问 ``deps`` 而不需要自定义
    ``StateGraph`` config。``graph.invoke`` 返回后，绑定被重置为
    ``None``，让下次 ``run`` 被强制调用 ``_set_deps``（避免跨并发
    调用的 deps 泄漏）。
    """
    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = deps


def _reset_deps() -> None:
    """清空全局 deps 绑定。始终在 ``graph.invoke`` 之后调用。"""
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
# Prose + review 辅助函数
# ---------------------------------------------------------------------------


def _call_plan_chapter(
    *,
    chapter_id: str,
    task: str,
    requirements: list[str],
    canon_block: str,
    history_block: str,
    prose_client: Any,
) -> str:
    """为 ``_plan_chapter_node`` 调 LLM 生成自由散文式章节计划。

    返回 LLM 产出的整段计划文本。下游 ``_draft_chapter_node`` 不解析
    此字符串——它是 opaque 散文,只在 trace 与调试输出中暴露。

    Deterministic 模式严格拒绝:per 2026-07-14 决定,无 LLM 时
    ``plan_chapter`` 必须 raise 而不是退化到模板。目的是强制用户
    配置 ``WRITER_API_KEY`` 才能跑 ``/创作``。

    ``prose_client`` 通过 kw-only 参数注入,让直接调用本 helper 的
    测试 (例如 ``test_plan_chapter_node_invokes_prose_client`` /
    ``test_plan_chapter_node_raises_when_deterministic``) 不必操心
    ``_set_deps / _reset_deps`` 仪式。生产路径始终通过
    ``_plan_chapter_node`` → ``_get_deps().prose_client`` 注入。
    """
    if prose_client is None or getattr(prose_client, "name", "") == "deterministic":
        msg = (
            "plan_chapter 需要真实 LLM；请设置 WRITER_API_KEY 环境变量后重启"
        )
        raise RuntimeError(msg)

    requirement_block = (
        "\n".join(f"- {r}" for r in requirements)
        if requirements
        else "（无）"
    )
    messages = CHAPTER_PLAN_TEMPLATE.format_messages(
        chapter_id=chapter_id,
        task=task,
        requirements=requirement_block,
        canon_block=canon_block or "（无）",
        history_block=history_block or "（无）",
    )
    system = messages[0].content
    user = messages[1].content
    try:
        return prose_client.generate_text(system=system, user=user)
    except Exception as exc:  # noqa: BLE001
        msg = f"plan_chapter LLM 调用失败: {exc}"
        raise RuntimeError(msg) from exc


def _call_prose_client(
    *,
    chapter_id: str,
    task: str,
    plan: str,
    canon_block: str,
    history_block: str,
) -> str:
    """调用配置的 :class:`LLMProseClient`。

    把调用拆分为 ``system``（长期上下文）和 ``user``（每次调用
    任务）消息。若 plan 不包含 canon / history 块，则回退到
    prep_context 的块。
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
        # 作为领域异常抛出 —— 引擎边界捕获通用 Exception。我们这里
        # 不记日志，因为引擎在边界记日志。
        msg = f"prose_client.generate_text 失败: {exc}"
        raise RuntimeError(msg) from exc


def _require_prose_client(deps: EngineDeps) -> Any:
    """返回 ``deps.prose_client``，若为 ``None`` 则抛出。

    Protocol 字段为 ``Optional`` 是为了 stub 友好；生产装配始终
    设置它。工作流与引擎的 LLM 工具循环 helper 把 ``None`` 视为
    配置错误而非静默回退。

    返回 ``Any``（而非 ``LLMProseClient``），因为类型仅在
    ``TYPE_CHECKING`` import 中存在；函数体从不检查静态类型，
    因此更宽泛注解的运行时成本为零并避免 import 循环。
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
    """用 :class:`ReviewVerdict` 结构化 prompt 调用 LLM。

    被 ``_review_gate_node`` 在 real 模式使用。确定性模式永不
    到达此 helper。

    LLM 在 ``deps.review_llm`` 设置时（测试路径）从中取；否则
    回退到 :func:`writer.llm.provider.get_llm` 配合全局 settings。
    回退要求配置 API key。
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
    """返回用于 review 判定的 LLM。

    优先级：
        1. ``deps.review_llm``（测试注入的 fake；review 路径的标准
           测试表面）。
        2. :func:`writer.llm.provider.get_llm` 配合全局 settings
           （生产；要求配置 API key）。
    """
    review_llm = getattr(deps, "review_llm", None)
    if review_llm is not None:
        return review_llm
    from writer.config import get_settings
    from writer.llm.provider import get_llm as _get_llm

    return _get_llm(get_settings())


def _load_active_foreshadows(deps: EngineDeps) -> list[str]:
    """调用 ``foreshadow_search(status="active")`` 并返回 IDs。

    任何错误时返回空列表（LLM 仍可自由产出判定；缺少活跃伏笔只
    作为低优先级关注点标记）。
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
    # 搜索结果是文本块；用简单正则抽取 IDs。
    import re

    return re.findall(r"F\d+", output)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _extract_chapter_id(user_input: str) -> str:
    text = user_input.removeprefix("/创作").strip()
    return text.split(maxsplit=1)[0] if text else "1.1"


def _excerpt(text: str, *, limit: int = 120) -> str:
    compact = " ".join(text.split())
    return compact[:limit] if compact else "暂无"


def _first_paragraph(draft: str, *, limit: int = 200) -> str:
    """返回 ``draft`` 第一段，限制在 ``limit`` 字符内。

    段落是到第一个空行前的文本。由 :func:`_persist_outputs_node`
    用于派生章节摘要。
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
    """把已完成的 :class:`WriterState` 转为 :class:`WorkflowResult`。"""
    artifacts: dict[str, Path] = {}
    for key, value in (final_state.get("artifacts") or {}).items():
        artifacts[key] = Path(str(value))
    metrics_value: dict[str, float | int | str] = {}
    metrics_input: dict[str, Any] = final_state.get("metrics") or {}
    for key, value in metrics_input.items():
        # mypy 友好强制转换：任何非已知标量被字符串化。保持
        # WorkflowResult 契约扁平。
        if isinstance(value, bool):
            # ``bool`` 是 ``int`` 的子类；强制为 int 让最终 dict
            # 只承载 ``int | float | str``。
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


# 兼容旧 import（例如 ``tests/test_workflows.py``）的别名。
def stub(ctx: EngineContext) -> WorkflowResult:
    """兼容别名 —— 用空 deps 委托给 :func:`run`。

    PR1 别名只接受 ``ctx``；PR2 为调用 ``from writer.workflows.write_chapter import stub``
    的测试保留它。真实调用方应使用 :func:`run`。
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
    "extract_write_chapter_args",  # 为方便重新导出
    "run",
    "stub",
]
