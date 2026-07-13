"""长篇章节工作流的上下文拼装。

工作流层向本模块请求现成的 ``ContextPack``，自身不执行检索。
这让上下文组装保持可替换：当前 MVP 使用本地文件拼装，
未来版本可以在同一函数背后接入更丰富的记忆存储。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

try:  # pragma: no cover - 仅当安装了 tiktoken 时才会间接触发
    import tiktoken
except ImportError:  # pragma: no cover - 极简环境的回退
    tiktoken = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ContextPack:
    """章节级任务的分层 prompt 素材。"""

    system_block: str
    canon_block: str
    history_block: str
    task_block: str
    token_audit: dict[str, int]


def prep_context(
    chapter_id: str,
    task: str,
    *,
    project_root: Path | None,
    max_tokens: int = 8_000,
) -> ContextPack:
    """为 ``chapter_id`` 和 ``task`` 构建并裁剪 ``ContextPack``。"""

    system_block = (
        "你是长篇小说写作工作流中的章节写作节点。必须遵守正典资料、延续前文因果，"
        "只在当前任务范围内创作。"
    )
    canon_block = _build_canon_block(project_root, query=f"{chapter_id} {task}")
    history_block = _build_history_block(project_root, chapter_id)
    task_block = f"当前章节: {chapter_id}\n当前任务: {task.strip() or '写作本章'}"

    pack = ContextPack(
        system_block=system_block,
        canon_block=canon_block,
        history_block=history_block,
        task_block=task_block,
        token_audit={},
    )
    return trim_to_budget(pack, max_tokens=max_tokens)


def trim_to_budget(pack: ContextPack, *, max_tokens: int = 8_000) -> ContextPack:
    """按确定策略裁剪上下文块并附带 token 审计数据。

    ``system_block`` 与 ``task_block`` 优先保留。预算紧张时，
    偏好保留 ``canon_block`` 而非 history_block —— 正典约束胜过复述细节。
    """

    remaining = max(max_tokens, 0)
    blocks: dict[str, str] = {}

    for field_name in ("system_block", "task_block", "canon_block", "history_block"):
        text = getattr(pack, field_name)
        trimmed, used = _take_tokens(text, remaining)
        blocks[field_name] = trimmed
        remaining -= used

    audit = {
        "system_block": count_tokens(blocks["system_block"]),
        "canon_block": count_tokens(blocks["canon_block"]),
        "history_block": count_tokens(blocks["history_block"]),
        "task_block": count_tokens(blocks["task_block"]),
    }
    audit["total"] = sum(audit.values())
    audit["budget"] = max_tokens

    return replace(pack, **blocks, token_audit=audit)


def count_tokens(text: str, *, model: str = "gpt-4o-mini") -> int:
    """使用 ``tiktoken`` 统计 token，缺失时回退到稳定的估算。"""

    if not text:
        return 0
    if tiktoken is None:
        return max(1, len(text) // 2)
    try:
        encoder = tiktoken.encoding_for_model(model)
    except KeyError:
        encoder = tiktoken.get_encoding("cl100k_base")
    return len(encoder.encode(text))


def _take_tokens(text: str, budget: int) -> tuple[str, int]:
    if budget <= 0 or not text:
        return "", 0
    cost = count_tokens(text)
    if cost <= budget:
        return text, cost

    if tiktoken is None:
        approx_chars = max(0, budget * 2)
        trimmed = text[:approx_chars].rstrip()
        return trimmed, count_tokens(trimmed)

    encoder = tiktoken.get_encoding("cl100k_base")
    tokens = encoder.encode(text)[:budget]
    trimmed = encoder.decode(tokens).rstrip()
    return trimmed, count_tokens(trimmed)


def _build_canon_block(project_root: Path | None, *, query: str) -> str:
    if project_root is None:
        return "未绑定项目，暂无正典资料。"

    # Per chg-remove-rag：纯文件拼装，无 RAG。分层为：
    #   1. 大纲/* 全文（小文件，整篇读）
    #   2. 人物/* 全文（小文件，整篇读）
    #   3. chapter_summaries.json 切片（按 chapter_id 前后 N=2 章）
    #   4. 最近一章 草稿/chapter-XXX.md 全文（"上一章" 笔触锚点）
    # ``query`` 参数仍保留在签名中以兼容 ``prep_context`` 调用方，
    # 但已不再使用：结构化分层在不依赖 embedder 的情况下也能给出相关素材。
    del query  # 之前会传入 ProjectRagIndex(...).query(query, ...)

    parts: list[str] = []
    for relative in ("大纲", "人物"):
        path = project_root / relative
        if path.exists():
            parts.extend(_read_markdown_files(path))

    summary_block = _build_summary_block(project_root)
    if summary_block:
        parts.append(summary_block)

    last_chapter = _read_last_chapter(project_root)
    if last_chapter:
        parts.append(last_chapter)

    return "\n\n".join(parts) if parts else "暂无正典资料。"


def _build_summary_block(project_root: Path) -> str:
    """为 canon block 返回章节摘要切片。

    读取 ``草稿/chapter_summaries.json`` 并产出小段头部 +
    最近若干条目（最多 4 条以保持块体积）。文件缺失 / 不可读时
    回退到「暂无章节摘要」。
    """

    summary_file = project_root / "草稿" / "chapter_summaries.json"
    summaries = _load_summary_json(summary_file)
    if not summaries:
        return ""
    recent = _select_recent_summaries(summaries, chapter_id="zzz", limit=4)
    if not recent:
        return ""
    return "[chapter_summaries]\n" + "\n".join(recent)


def _read_last_chapter(project_root: Path) -> str:
    """将最近的 ``草稿/chapter-*.md`` 作为 canon anchor 返回。

    无草稿文件时返回 ""。文件以 ``[last_chapter]`` 前缀，
    让下游消费者一眼能看出素材来源。
    """

    manuscript = project_root / "草稿"
    if not manuscript.exists():
        return ""
    candidates = sorted(
        path for path in manuscript.glob("chapter-*.md")
        if path.is_file()
    )
    if not candidates:
        return ""
    last = candidates[-1]
    try:
        text = last.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    if not text:
        return ""
    return f"[last_chapter:{last.name}]\n{text}"


def _build_history_block(project_root: Path | None, chapter_id: str) -> str:
    if project_root is None:
        return "暂无历史章节摘要。"

    summary_file = project_root / "草稿" / "chapter_summaries.json"
    summaries = _load_summary_json(summary_file)
    if summaries:
        nearby = _select_recent_summaries(summaries, chapter_id, limit=3)
        if nearby:
            return "\n".join(nearby)

    manuscript = project_root / "草稿"
    if manuscript.exists():
        chapters = _read_markdown_files(manuscript)
        return "\n\n".join(chapters[-3:]) if chapters else "暂无历史章节摘要。"
    return "暂无历史章节摘要。"


def _load_summary_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _select_recent_summaries(
    summaries: dict[str, Any],
    chapter_id: str,
    *,
    limit: int,
) -> list[str]:
    selected: list[str] = []
    for key in sorted(summaries):
        if key >= chapter_id:
            continue
        value = summaries[key]
        if isinstance(value, str):
            selected.append(f"{key}: {value}")
        elif isinstance(value, dict):
            summary = value.get("summary") or value.get("摘要")
            if isinstance(summary, str):
                selected.append(f"{key}: {summary}")
    return selected[-limit:]


def _read_markdown_files(root: Path) -> list[str]:
    files = [root] if root.is_file() else sorted(root.rglob("*"))
    blocks: list[str] = []
    for path in files:
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        if any(part.startswith(".") for part in path.relative_to(root if root.is_dir() else path.parent).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            continue
        if text:
            blocks.append(f"[{path.name}]\n{text}")
    return blocks


__all__ = ["ContextPack", "count_tokens", "prep_context", "trim_to_budget"]
