"""LangGraph ``skeleton_chapters`` 工作流（per ``chg-skeleton-chapters-pr1``）。

PR1 落地 ``/骨架`` 命令的 workflow 形态：在已有 ``大纲/大纲.md`` +
``大纲/章节目录.md`` 上为每章生成「开头 + 结尾」骨架，落盘到
``骨架/<卷>/第N章.md``，作为 PR3 ``/创作`` prep_context 的边界约束输入。

图是 6 节点 Plan-Execute 管道：

``load_inputs -> parse_toc -> init_or_load_progress -> generate_batch -> persist_skeleton -> finalize``

节点调用激活的 :class:`RunnerDeps` 进行散文生成
（``deps.prose_client.generate_text``）。``persist_skeleton`` 终结节点直接
用 :meth:`Path.write_text` 写骨架文件（与 ``write_chapter._persist_outputs_node``
同款），**不**经 ``safe_write_file`` 工具，**不**扩 ``DEFAULT_WRITE_WHITELIST``。

PR1 范围外（推后续 PR）：

* ``view`` 短路（PR1.5）
* ``continue`` 续跑 + ``进度.json`` 进度文件 + ``rewrite`` 覆盖（PR2）
* CLI 启动 deterministic 警告扩 ``/骨架``（PR2.5）
* ``prompts/context.py::_build_canon_block`` 元组追加 ``"骨架"``（PR3）

返回类型是 :class:`WorkflowResult`：引擎把 ``status="completed"``
映射到 ``Done(reason="workflow_completed", ...)``；``status="failed"``
携带 ``metrics["partial_chapters"]`` 表达部分完成（per design decision 6）。
``status="pending"`` **不**用于 ``skeleton_chapters``——runner 把 pending
专用于 ``needs_rewrite`` 单义。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from writer.project.state import detect_state
from writer.workflows.params import SkeletonArgs, extract_skeleton_args
from writer.workflows.types import WorkflowResult

if TYPE_CHECKING:
    from writer.runner.context import RunnerContext
    from writer.runner.deps import RunnerDeps


# ---------------------------------------------------------------------------
# 模块级常量（per TODO/骨架命令.md §5；与 write_chapter.REVIEW_THRESHOLD 同款）
# ---------------------------------------------------------------------------

OPEN_MAX_CHARS = 400
"""单章「## 开头」段落字符上限。"""

CLOSE_MAX_CHARS = 300
"""单章「## 结尾」段落字符上限。"""

PREV_CLOSING_BUDGET = 500
"""``prev_closing`` 串递时的字符上限，避免 prompt 膨胀（per design decision risks §L4）。"""

_PROJECT_STATE_MIN = "S3"
"""``/骨架`` 最低允许项目状态。``S3 = HAS_TOC`` 含义是章节目录已生成。"""


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State TypedDict
# ---------------------------------------------------------------------------


class SkeletonState(TypedDict, total=False):
    """LangGraph skeleton_chapters 图的状态。

    在 LangGraph `StateGraph` 的 partial update 语义下，节点返回 dict
    的 keys 是要更新的字段（未返回的保持原值）。``trace`` 用 list 累加
    节点名以做调试用（与 write_chapter.WriterState 一致）。
    """

    project_root: str
    args: dict  # asdict(SkeletonArgs)
    canon_meta: dict  # {"genre": str, "architecture_method": str, "agent_md_path": str}
    toc_path: str  # str(Path("大纲/章节目录.md"))— 由 load_inputs 写入,parse_toc 读取
    toc: list[dict]  # [{"chapter_id": "1.1", "title": "...", "volume": "卷一", "toc_blurb": "..."}]
    tasks: list[dict]  # 过滤后的章节任务（按 mode/volume/start/end 筛选）
    cursor: int
    prev_closing: str
    completed_ids: list[str]
    failed_at: str  # 失败时的 chapter_id（用于 partial_chapters 报告）
    trace: list[str]
    artifacts: dict
    metrics: dict
    error: str  # 非空时下游节点短路到 finalize


# ---------------------------------------------------------------------------
# 模块级 deps 注入（per write_chapter.py:367-396）
# ---------------------------------------------------------------------------

_WORKFLOW_DEPS: RunnerDeps | None = None


def _set_deps(deps: RunnerDeps) -> None:
    """把 ``deps`` 绑定为下一次图调用的激活依赖。

    由 :func:`run` 调用。绑定刻意是全局的，让 LangGraph 的裸函数节点
    签名仍能访问 ``deps`` 而不需要自定义 ``StateGraph`` config。
    ``graph.invoke`` 返回后绑定被重置为 ``None``，避免跨并发调用的
    deps 泄漏。
    """

    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = deps


def _reset_deps() -> None:
    """清空全局 deps 绑定。始终在 ``graph.invoke`` 之后调用。"""

    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = None


def _get_deps() -> RunnerDeps:
    if _WORKFLOW_DEPS is None:
        msg = (
            "skeleton_chapters node called without _set_deps; "
            "call _set_deps(deps) before graph.invoke"
        )
        raise RuntimeError(msg)
    return _WORKFLOW_DEPS


def _require_prose_client(deps: RunnerDeps) -> Any:
    """返回 ``deps.prose_client``，若为 ``None`` 则抛出。"""

    client = deps.prose_client
    if client is None:
        msg = (
            "RunnerDeps.prose_client is None; "
            "production_deps always sets it, so this is a wiring bug"
        )
        raise RuntimeError(msg)
    return client


# ---------------------------------------------------------------------------
# 节点实现
# ---------------------------------------------------------------------------


def _load_inputs_node(state: SkeletonState) -> SkeletonState:
    """校验 project_root / project_state / 必需文件；读 AGENT.md 双行。

    ``project_state >= S3``（HAS_TOC）的检查通过 ``detect_state`` 实做
    —— 文件存在性是 source of truth。任一校验失败设 ``state["error"]``
    让下游短路到 finalize。
    """

    raw_root = state.get("project_root", "")
    project_root = Path(raw_root).resolve() if raw_root else None

    if project_root is None or not (project_root / "AGENT.md").is_file():
        return {
            "error": "未绑定项目，请先执行 writer new <书名>",
            "trace": [*state.get("trace", []), "load_inputs"],
        }

    detected = detect_state(project_root)
    # ProjectState 是有序 StrEnum；与 S3 比较即"是否达到 HAS_TOC"
    if detected.value < _PROJECT_STATE_MIN:
        return {
            "error": f"项目状态 < S3（当前 {detected.value}），请先执行 /目录",
            "trace": [*state.get("trace", []), "load_inputs"],
        }

    if not (project_root / "大纲" / "大纲.md").is_file():
        return {
            "error": "缺少 大纲/大纲.md，请先执行 /大纲",
            "trace": [*state.get("trace", []), "load_inputs"],
        }

    toc_path = project_root / "大纲" / "章节目录.md"
    if not toc_path.is_file():
        return {
            "error": "缺少 大纲/章节目录.md，请先执行 /目录",
            "trace": [*state.get("trace", []), "load_inputs"],
        }

    # 读 AGENT.md 双行（per MEMORY 2026-07-16 decision）
    from writer.project.state import (
        read_architecture_method_from_agent,
        read_genre_from_agent,
    )

    agent_md = project_root / "AGENT.md"
    canon_meta = {
        "genre": read_genre_from_agent(agent_md),
        "architecture_method": read_architecture_method_from_agent(agent_md),
        "agent_md_path": str(agent_md),
    }

    return {
        "canon_meta": canon_meta,
        "toc_path": str(toc_path),
        "trace": [*state.get("trace", []), "load_inputs"],
    }


def _parse_toc_node(state: SkeletonState) -> SkeletonState:
    """解析章节目录 → ``state["toc"]`` + 按 args 过滤 → ``state["tasks"]``。

    PR1 解析使用简单的正则匹配 ``第\\s*<id>\\s*章`` / ``<id>.\\s+<title>``
    两种形式——章节目录 SKILL.md 不强制单一格式，足够 MVP 覆盖。若解析
    不到任何章节则设 ``error``。
    """

    if state.get("error"):
        return {"trace": [*state.get("trace", []), "parse_toc"]}

    toc_path = Path(state["toc_path"])  # type: ignore[arg-type]
    args = SkeletonArgs(**state["args"])  # 重建 dataclass

    raw_toc = toc_path.read_text(encoding="utf-8")
    toc_entries = _parse_toc_text(raw_toc)

    if not toc_entries:
        return {
            "error": "章节目录解析为空，请检查 大纲/章节目录.md 格式",
            "trace": [*state.get("trace", []), "parse_toc"],
        }

    # 按 mode 过滤
    tasks = _filter_tasks(toc_entries, args)

    if not tasks:
        return {
            "error": f"无匹配章节 (mode={args.mode} volume={args.volume!r} range={args.start}-{args.end})",
            "trace": [*state.get("trace", []), "parse_toc"],
        }

    return {
        "toc": toc_entries,
        "tasks": tasks,
        "trace": [*state.get("trace", []), "parse_toc"],
    }


def _init_or_load_progress_node(state: SkeletonState) -> SkeletonState:
    """PR1 仅写一份新的 ``骨架/进度.json``，**不**读旧进度。

    Continue 语义在 PR2 落地（per TODO/骨架命令.md §12）。
    """

    if state.get("error"):
        return {"trace": [*state.get("trace", []), "init_or_load_progress"]}

    project_root = Path(state["project_root"])
    progress_dir = project_root / "骨架"
    progress_dir.mkdir(parents=True, exist_ok=True)
    progress_path = progress_dir / "进度.json"

    payload = {
        "status": "running",
        "mode": state["args"].get("mode", "full"),
        "rewrite": state["args"].get("rewrite", False),
        "completed": [],
        "current": None,
        "updated_at": _now_iso(),
    }
    progress_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "cursor": 0,
        "prev_closing": "",
        "completed_ids": [],
        "trace": [*state.get("trace", []), "init_or_load_progress"],
    }


def _generate_batch_node(state: SkeletonState) -> SkeletonState:
    """对每个章节调一次 ``prose_client.generate_text`` 拿开+收。

    PR1 串行（per TODO/骨架命令.md §10）。章节内：

    1. ``_build_chapter_prompt`` 拼 (system, user) prompt
    2. ``_call_generate_open_close`` 调 LLM + 解析 ``## 开头`` / ``## 结尾``
    3. ``persist_skeleton_node`` 落盘（per LangGraph partial update，
       本节点直接落盘 + 更新 state；不拆两个节点）
    4. ``prev_closing`` 串递给下一章 prompt
    """

    if state.get("error"):
        return {"trace": [*state.get("trace", []), "generate_batch"]}

    deps = _get_deps()
    prose_client = _require_prose_client(deps)
    project_root = Path(state["project_root"])

    tasks: list[dict] = state["tasks"]
    canon_meta: dict = state.get("canon_meta", {})  # type: ignore[assignment]

    completed_ids: list[str] = list(state.get("completed_ids", []))
    prev_closing = state.get("prev_closing", "")

    progress_path = project_root / "骨架" / "进度.json"

    for task in tasks:
        chapter_id = task["chapter_id"]
        try:
            opening, closing = _call_generate_open_close(
                prose_client=prose_client,
                chapter_id=chapter_id,
                title=task.get("title", ""),
                volume=task.get("volume", ""),
                toc_blurb=task.get("toc_blurb", ""),
                prev_closing=prev_closing,
                genre=canon_meta.get("genre", ""),
                architecture_method=canon_meta.get("architecture_method", ""),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("skeleton_chapters 中断 @ %s: %s", chapter_id, exc)
            # 写进度为 failed 后上抛；run() 收口构造 WorkflowResult
            _update_progress(progress_path, status="failed", current=chapter_id)
            return {
                "error": str(exc),
                "failed_at": chapter_id,
                "completed_ids": completed_ids,
                "trace": [*state.get("trace", []), "generate_batch"],
            }

        # 落盘（per LangGraph partial update；不拆 persist_skeleton_node）
        _write_chapter_file(
            project_root=project_root,
            chapter_id=chapter_id,
            title=task.get("title", ""),
            volume=task.get("volume", ""),
            toc_blurb=task.get("toc_blurb", ""),
            opening=opening,
            closing=closing,
        )
        completed_ids.append(chapter_id)
        prev_closing = closing
        _update_progress(
            progress_path,
            status="running",
            current=chapter_id,
            completed=completed_ids,
        )

    return {
        "completed_ids": completed_ids,
        "prev_closing": prev_closing,
        "trace": [*state.get("trace", []), "generate_batch"],
    }


def _persist_skeleton_node(state: SkeletonState) -> SkeletonState:
    """空节点占位。

    PR1 把落盘合并到 ``_generate_batch_node``（每章生成后立即写盘）。
    本节点保留以便 PR2 续跑逻辑（continue 时跳过整节点）和 PR3
    索引/汇总拆分时使用。
    """

    return {"trace": [*state.get("trace", []), "persist_skeleton"]}


def _finalize_node(state: SkeletonState) -> SkeletonState:
    """写 ``骨架/索引.md`` + 构造 ``WorkflowResult``。

    索引是全书开/收一行摘要表（per TODO/骨架命令.md §5）。
    """

    error = state.get("error")
    completed_ids: list[str] = list(state.get("completed_ids", []))
    tasks: list[dict] = state.get("tasks", [])  # type: ignore[assignment]
    args = state["args"]

    project_root = Path(state["project_root"])

    if error:
        # 部分完成：metrics 用 partial_chapters 表达
        # 真正的 WorkflowResult 在 run() 里包
        artifacts: dict[str, str] = state.get("artifacts", {})  # type: ignore[assignment]
        artifacts["progress_path"] = str(project_root / "骨架" / "进度.json")
        metrics: dict[str, float | int | str] = {
            "error": str(error),
            "partial_chapters": len(completed_ids),
            "mode": str(args.get("mode", "full")),
            "volume": str(args.get("volume", "")),
        }
        return {
            "artifacts": artifacts,
            "metrics": metrics,
            "trace": [*state.get("trace", []), "finalize"],
        }

    # 成功：写索引 + 填 metrics
    index_path = project_root / "骨架" / "索引.md"
    _write_index(index_path, tasks, completed_ids)

    artifacts = {
        "skeleton_root": str(project_root / "骨架"),
        "index_path": str(index_path),
        "progress_path": str(project_root / "骨架" / "进度.json"),
    }
    metrics = {
        "chapter_count": len(completed_ids),
        "mode": str(args.get("mode", "full")),
        "volume": str(args.get("volume", "")),
        "rewrite": 0,
        "resumed": 0,
    }
    return {
        "artifacts": artifacts,
        "metrics": metrics,
        "trace": [*state.get("trace", []), "finalize"],
    }


# ---------------------------------------------------------------------------
# 图拓扑
# ---------------------------------------------------------------------------


def build_skeleton_graph(*, checkpointer: Any | None = None) -> CompiledStateGraph:
    """构建 6 节点 skeleton_chapters 图。

    节点：
        load_inputs -> parse_toc -> init_or_load_progress -> generate_batch
        -> persist_skeleton -> finalize -> END
    """

    graph = StateGraph(SkeletonState)
    graph.add_node("load_inputs", _load_inputs_node)
    graph.add_node("parse_toc", _parse_toc_node)
    graph.add_node("init_or_load_progress", _init_or_load_progress_node)
    graph.add_node("generate_batch", _generate_batch_node)
    graph.add_node("persist_skeleton", _persist_skeleton_node)
    graph.add_node("finalize", _finalize_node)

    graph.set_entry_point("load_inputs")
    graph.add_edge("load_inputs", "parse_toc")
    graph.add_edge("parse_toc", "init_or_load_progress")
    graph.add_edge("init_or_load_progress", "generate_batch")
    graph.add_edge("generate_batch", "persist_skeleton")
    graph.add_edge("persist_skeleton", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------


def run(ctx: RunnerContext, deps: RunnerDeps) -> WorkflowResult:
    """构建图，运行它，并返回 :class:`WorkflowResult`。

    与 ``write_chapter.run`` 同款的 (ctx, deps) → WorkflowResult 契约。
    PR1 ``init_or_load_progress`` 用 MemorySaver（无 SQLite 持久化——续跑
    推 PR2）。``thread_id`` 用 session_id 或 mode 派生，确保同一输入跨
    REPL 轮次可恢复。
    """

    args = extract_skeleton_args(ctx.user_input)
    initial_state: SkeletonState = {
        "project_root": str(ctx.project_root) if ctx.project_root is not None else "",
        "args": asdict(args),
        "trace": [],
        "artifacts": {},
        "metrics": {},
    }

    checkpointer, close_checkpointer = _build_checkpointer(ctx.project_root)
    graph = build_skeleton_graph(checkpointer=checkpointer)
    config = {
        "configurable": {
            "thread_id": ctx.session_id or f"skeleton-{args.mode}-{id(ctx)}"
        }
    }
    _set_deps(deps)
    try:
        final_state = cast(
            SkeletonState, cast(Any, graph).invoke(initial_state, config=config)
        )
    finally:
        close_checkpointer()
        _reset_deps()

    return _state_to_result(final_state, mode=args.mode, volume=args.volume)


# ---------------------------------------------------------------------------
# TOC 解析 / 任务过滤
# ---------------------------------------------------------------------------


_TOC_LINE_PATTERNS = (
    # "第 1.1 章 · 标题" 或 "第 1.1 章 标题"（首选,最不易误判）
    re.compile(r"^第\s*(?P<id>\d+\.\d+)\s*章[·\s]+(?P<title>.+?)$"),
)

_VOLUME_HEADER_PATTERN = re.compile(r"^(卷[一二三四五六七八九十]+)\s*$")


def _parse_toc_text(text: str) -> list[dict]:
    """把 ``大纲/章节目录.md`` 解析为 ``list[dict]``。

    输出形如::

        [{"chapter_id": "1.1", "title": "...", "volume": "卷一", "toc_blurb": "..."}]

    ``toc_blurb`` 取该章节下方到下一章节前的首段非标题文本；若没有则为
    空字符串。

    PR1 解析容错：忽略空行、`##` / `#` 标题行、不匹配章节行；遇到
    ``卷N`` 单行视为卷名 header，后续章节绑定到该卷。
    """

    entries: list[dict] = []
    current_volume = ""
    current_entry: dict | None = None
    blurb_lines: list[str] = []

    def _flush_entry() -> None:
        if current_entry is not None:
            current_entry["toc_blurb"] = " ".join(blurb_lines).strip()[:200]
            entries.append(current_entry)

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("#"):
            # 跳过 markdown 标题
            continue

        volume_match = _VOLUME_HEADER_PATTERN.match(line.strip())
        if volume_match is not None:
            _flush_entry()
            current_entry = None
            blurb_lines = []
            current_volume = volume_match.group(1)
            continue

        matched = False
        for pattern in _TOC_LINE_PATTERNS:
            m = pattern.match(line.strip())
            if m is not None:
                _flush_entry()
                current_entry = {
                    "chapter_id": m.group("id"),
                    "title": m.group("title").strip(),
                    "volume": current_volume,
                    "toc_blurb": "",
                }
                blurb_lines = []
                matched = True
                break

        if not matched and current_entry is not None:
            blurb_lines.append(line.strip())

    _flush_entry()
    return entries


def _filter_tasks(toc: list[dict], args: SkeletonArgs) -> list[dict]:
    """按 ``SkeletonArgs.mode`` 过滤章节列表。

    PR1 区间过滤用「同卷起点」语义（per TODO/骨架命令.md §9 + design risks）：
    start 与 end 同卷时按章节号字典序截取；跨卷时取 start 卷起点到 end
    卷终点。PR2 细化跨卷语义。
    """

    if args.mode == "full":
        return list(toc)

    if args.mode == "volume":
        return [t for t in toc if t.get("volume") == args.volume]

    if args.mode == "range":
        try:
            start_vol, start_chap = (int(x) for x in args.start.split("."))
            end_vol, end_chap = (int(x) for x in args.end.split("."))
        except ValueError:
            return []

        results = []
        for t in toc:
            try:
                t_vol, t_chap = (int(x) for x in t["chapter_id"].split("."))
            except (KeyError, ValueError):
                continue
            # 区间：[start_vol.start_chap, end_vol.end_chap]
            if (t_vol, t_chap) < (start_vol, start_chap):
                continue
            if (t_vol, t_chap) > (end_vol, end_chap):
                continue
            results.append(t)
        return results

    return []


# ---------------------------------------------------------------------------
# LLM 调用 helper
# ---------------------------------------------------------------------------


def _build_chapter_prompt(
    *,
    chapter_id: str,
    title: str,
    volume: str,
    toc_blurb: str,
    prev_closing: str,
    genre: str,
    architecture_method: str,
) -> tuple[str, str]:
    """为本章生成 ``(system, user)`` prompt 对。

    ``system`` 注入题材 + 架构方法 + 字数约束；``user`` 注入章节信息
    + 上章结尾（截 ``PREV_CLOSING_BUDGET`` 字符）。与
    ``write_chapter._call_prose_client`` 同款的 (system, user) 拆分。
    """

    system = (
        f"你是长篇小说「骨架」生成节点。\n"
        f"\n"
        f"题材：{genre or '未知'}\n"
        f"架构方法：{architecture_method or '雪花法'}\n"
        f"\n"
        f"约束：\n"
        f"- 每章只输出「## 开头」（≤ {OPEN_MAX_CHARS} 字）与「## 结尾」（≤ {CLOSE_MAX_CHARS} 字）两段\n"
        f"- 开头：场景切入、人物在场、本章初始冲突钩子；禁止写完整高潮；禁止泄终局\n"
        f"- 结尾：本章收束势 + 通向下一章的钩子；本卷末章可收卷不硬留钩\n"
        f"- 语气贴题材（玄幻/历史/言情/其他）\n"
        f"\n"
        f"输出 Markdown 模板：\n"
        f"```markdown\n"
        f"## 开头\n"
        f"<200-400 字>\n"
        f"\n"
        f"## 结尾\n"
        f"<150-300 字>\n"
        f"```\n"
    )

    user = (
        f"章节信息：\n"
        f"- chapter_id: {chapter_id}\n"
        f"- volume: {volume or '未分卷'}\n"
        f"- 目录标题: {title}\n"
        f"- 目录摘要: {toc_blurb or '（无）'}\n"
    )

    if prev_closing:
        truncated = prev_closing[:PREV_CLOSING_BUDGET]
        suffix = "\n…（截断）" if len(prev_closing) > PREV_CLOSING_BUDGET else ""
        user += f"\n上章「结尾」承接：\n{truncated}{suffix}\n"

    return system, user


def _call_generate_open_close(
    *,
    prose_client: Any,
    chapter_id: str,
    title: str,
    volume: str,
    toc_blurb: str,
    prev_closing: str,
    genre: str,
    architecture_method: str,
) -> tuple[str, str]:
    """调 LLM 拿 ``(opening, closing)``。

    Deterministic 模式 strict raise（per design decision 4，与
    ``write_chapter._call_plan_chapter:428-432`` 同款）。

    输出解析：按 ``## 开头`` / ``## 结尾`` 切分；解析失败重试 1 次；
    再失败抛 ``RuntimeError("skeleton_chapter 单章生成失败")``。
    """

    if prose_client is None or getattr(prose_client, "name", "") == "deterministic":
        msg = (
            "skeleton_chapter 需要真实 LLM；请设置 WRITER_API_KEY 环境变量后重启"
        )
        raise RuntimeError(msg)

    def _attempt() -> tuple[str, str]:
        system, user = _build_chapter_prompt(
            chapter_id=chapter_id,
            title=title,
            volume=volume,
            toc_blurb=toc_blurb,
            prev_closing=prev_closing,
            genre=genre,
            architecture_method=architecture_method,
        )
        try:
            raw = prose_client.generate_text(system=system, user=user)
        except Exception as exc:  # noqa: BLE001
            msg = f"prose_client.generate_text 失败: {exc}"
            raise RuntimeError(msg) from exc
        return _parse_open_close(raw)

    try:
        return _attempt()
    except (ValueError, KeyError):
        # 解析失败重试一次
        return _attempt()


_OPEN_HEADER = "## 开头"
_CLOSE_HEADER = "## 结尾"


def _parse_open_close(raw: str) -> tuple[str, str]:
    """从 LLM 输出切 ``## 开头`` / ``## 结尾`` 两段。"""

    if not raw or _OPEN_HEADER not in raw or _CLOSE_HEADER not in raw:
        raise ValueError(f"LLM 输出缺少 {_OPEN_HEADER} 或 {_CLOSE_HEADER} 段落")

    after_open = raw.split(_OPEN_HEADER, 1)[1]
    parts = after_open.split(_CLOSE_HEADER, 1)
    opening = parts[0].strip()
    closing = parts[1].strip() if len(parts) > 1 else ""

    if not opening:
        raise ValueError(f"{_OPEN_HEADER} 段为空")
    if not closing:
        raise ValueError(f"{_CLOSE_HEADER} 段为空")

    # 字数上限裁剪（按 char 近似；中英文混排时也合理）
    if len(opening) > OPEN_MAX_CHARS * 2:
        opening = opening[: OPEN_MAX_CHARS * 2]
    if len(closing) > CLOSE_MAX_CHARS * 2:
        closing = closing[: CLOSE_MAX_CHARS * 2]

    return opening, closing


# ---------------------------------------------------------------------------
# 落盘 helper
# ---------------------------------------------------------------------------


def _seq_from_chapter_id(chapter_id: str) -> int:
    """``"1.3"`` → ``3``，``"2.10"`` → ``10``。卷号忽略（同一卷内序号）。"""

    try:
        _, chap = chapter_id.split(".", 1)
        return int(chap)
    except (ValueError, AttributeError):
        return 0


def _write_chapter_file(
    *,
    project_root: Path,
    chapter_id: str,
    title: str,
    volume: str,
    toc_blurb: str,
    opening: str,
    closing: str,
) -> Path:
    """落盘 ``<project_root>/骨架/<volume>/第{seq:03d}章.md``。"""

    safe_volume = volume or "未分卷"
    target_dir = project_root / "骨架" / safe_volume
    target_dir.mkdir(parents=True, exist_ok=True)
    seq = _seq_from_chapter_id(chapter_id)
    chapter_path = target_dir / f"第{seq:03d}章.md"

    body = (
        f"# 第 {chapter_id} 章 · {title}\n"
        f"\n"
        f"## 元信息\n"
        f"\n"
        f"- chapter_id: {chapter_id}\n"
        f"- volume: {volume or '未分卷'}\n"
        f"- 目录摘要: {toc_blurb or '（无）'}\n"
        f"\n"
        f"## 开头\n"
        f"\n"
        f"{opening}\n"
        f"\n"
        f"## 结尾\n"
        f"\n"
        f"{closing}\n"
        f"\n"
        f"## 衔接备注\n"
        f"\n"
        f"- 承接上章: （见上章结尾）\n"
        f"- 交给下章: （见本章结尾）\n"
    )
    chapter_path.write_text(body, encoding="utf-8")
    return chapter_path


def _write_index(
    index_path: Path, tasks: list[dict], completed_ids: list[str]
) -> None:
    """写 ``骨架/索引.md``——全书开/收一行摘要表。"""

    rows: list[str] = []
    rows.append("# 骨架索引\n")
    rows.append("\n")
    rows.append("| chapter_id | 卷 | 标题 | 开头摘要 | 结尾摘要 |\n")
    rows.append("| --- | --- | --- | --- | --- |\n")

    completed_set = set(completed_ids)
    proj_root = index_path.parent.parent  # 骨架/索引.md → project_root
    for task in tasks:
        if task["chapter_id"] not in completed_set:
            continue
        chapter_id = task["chapter_id"]
        title = task.get("title", "")
        volume = task.get("volume", "")
        seq = _seq_from_chapter_id(chapter_id)
        safe_volume = volume or "未分卷"
        actual_chapter_path = proj_root / "骨架" / safe_volume / f"第{seq:03d}章.md"

        try:
            content = actual_chapter_path.read_text(encoding="utf-8")
            opening_summary = _first_section_text(content, "## 开头", limit=30)
            closing_summary = _first_section_text(content, "## 结尾", limit=30)
        except OSError:
            opening_summary = "（文件读取失败）"
            closing_summary = "（文件读取失败）"

        rows.append(
            f"| {chapter_id} | {safe_volume} | {title} | {opening_summary} | {closing_summary} |\n"
        )

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("".join(rows), encoding="utf-8")


def _first_section_text(content: str, header: str, *, limit: int = 30) -> str:
    """提取 markdown 中 ``header`` 段落的纯文本前 ``limit`` 字。"""

    if header not in content:
        return ""
    after = content.split(header, 1)[1]
    # 取下一个 ## 或文末
    next_section = re.search(r"^## ", after, re.MULTILINE)
    section_body = after[: next_section.start()] if next_section else after
    # 取首段非空
    for para in section_body.strip().split("\n\n"):
        text = para.strip()
        if text:
            return text[:limit] + ("…" if len(text) > limit else "")
    return ""


def _update_progress(
    progress_path: Path,
    *,
    status: str,
    current: str | None = None,
    completed: list[str] | None = None,
) -> None:
    """更新 ``骨架/进度.json``。"""

    payload: dict[str, Any] = {
        "status": status,
        "current": current,
        "updated_at": _now_iso(),
    }
    if completed is not None:
        payload["completed"] = completed
    try:
        existing = json.loads(progress_path.read_text(encoding="utf-8"))
        existing.update(payload)
        progress_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError):
        # 进度文件丢失或损坏——以新内容回写
        payload.setdefault("completed", [])
        payload.setdefault("mode", "full")
        payload.setdefault("rewrite", False)
        progress_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串。"""

    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# WorkflowResult 适配
# ---------------------------------------------------------------------------


def _state_to_result(
    final_state: SkeletonState, *, mode: str, volume: str
) -> WorkflowResult:
    """把已完成的 :class:`SkeletonState` 转为 :class:`WorkflowResult`（per design decision 6）。

    部分完成用 ``status="failed"`` + ``metrics["partial_chapters"]`` 表达。
    """

    error = final_state.get("error")
    completed_ids: list[str] = list(final_state.get("completed_ids", []))
    trace: list[str] = list(final_state.get("trace", []))
    raw_metrics: dict = final_state.get("metrics", {}) or {}
    raw_artifacts: dict = final_state.get("artifacts", {}) or {}

    artifacts: dict[str, Path] = {
        k: Path(str(v)) for k, v in raw_artifacts.items() if isinstance(v, (str, Path))
    }

    metrics_value: dict[str, float | int | str] = {}
    for key, value in raw_metrics.items():
        if isinstance(value, bool):
            metrics_value[key] = int(value)
        elif isinstance(value, (int, float, str)):
            metrics_value[key] = value
        else:
            metrics_value[key] = str(value)

    if error:
        chunks: tuple[str, ...] = (
            f"[workflow] skeleton_chapters 中断; 已完成 {len(completed_ids)} 章\n",
            f"[workflow] error: {error}\n",
            "[workflow] trace=" + " → ".join(trace) + "\n",
        )
        return WorkflowResult(
            status="failed",
            chunks=chunks,
            artifacts=artifacts,
            metrics=metrics_value,
        )

    chunks = (
        "[workflow] skeleton_chapters 完成\n",
        f"[workflow] mode={mode} volume={volume or '-'} chapter_count={len(completed_ids)}\n",
        "[workflow] trace=" + " → ".join(trace) + "\n",
    )
    return WorkflowResult(
        status="completed",
        chunks=chunks,
        artifacts=artifacts,
        metrics=metrics_value,
    )


# ---------------------------------------------------------------------------
# Checkpointer（per write_chapter._build_checkpointer 模式）
# ---------------------------------------------------------------------------


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


__all__ = [
    "CLOSE_MAX_CHARS",
    "OPEN_MAX_CHARS",
    "PREV_CLOSING_BUDGET",
    "SkeletonState",
    "build_skeleton_graph",
    "run",
]
