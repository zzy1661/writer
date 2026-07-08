"""Context packing for long-form chapter workflows.

The workflow layer asks this module for a ready-to-use ``ContextPack`` and
does not perform retrieval itself. That keeps context assembly replaceable:
the current MVP uses local files and project RAG, while future versions can
swap in richer memory stores behind the same function.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised indirectly when tiktoken is installed
    import tiktoken
except ImportError:  # pragma: no cover - fallback for minimal environments
    tiktoken = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ContextPack:
    """Layered prompt material for a chapter-level task."""

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
    """Build and trim a ``ContextPack`` for ``chapter_id`` and ``task``."""

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
    """Trim context blocks deterministically and attach token audit data.

    ``system_block`` and ``task_block`` are kept first. ``canon_block`` is
    preferred over history because正典约束 beats recap detail when budget is tight.
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
    """Count tokens with ``tiktoken`` and fall back to a stable estimate."""

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

    # Per chg-remove-rag: pure file composition, no RAG. Layers are:
    #   1. outline/* 全文（小文件，整篇读）
    #   2. characters/* 全文（小文件，整篇读）
    #   3. chapter_summaries.json 切片（按 chapter_id 前后 N=2 章）
    #   4. 最近一章 manuscript/chapter-XXX.md 全文（"上一章" 笔触锚点）
    # The `query` parameter is kept in the signature for back-compat with
    # `prep_context` callers but is no longer used: structured layers
    # give us the relevant content without needing an embedder.
    del query  # formerly fed into ProjectRagIndex(...).query(query, ...)

    parts: list[str] = []
    for relative in ("outline", "characters"):
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
    """Return the chapter-summaries slice for the canon block.

    Reads ``manuscript/chapter_summaries.json`` and emits a small
    header + the last few entries (capped at 4 to keep the block small).
    Falls back to "暂无章节摘要" on missing / unreadable file.
    """

    summary_file = project_root / "manuscript" / "chapter_summaries.json"
    summaries = _load_summary_json(summary_file)
    if not summaries:
        return ""
    recent = _select_recent_summaries(summaries, chapter_id="zzz", limit=4)
    if not recent:
        return ""
    return "[chapter_summaries]\n" + "\n".join(recent)


def _read_last_chapter(project_root: Path) -> str:
    """Return the most recent ``manuscript/chapter-*.md`` as a canon anchor.

    Returns "" when no manuscript files exist. The file is prefixed with
    ``[last_chapter]`` so downstream consumers can see at a glance where
    the content came from.
    """

    manuscript = project_root / "manuscript"
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

    summary_file = project_root / "manuscript" / "chapter_summaries.json"
    summaries = _load_summary_json(summary_file)
    if summaries:
        nearby = _select_recent_summaries(summaries, chapter_id, limit=3)
        if nearby:
            return "\n".join(nearby)

    manuscript = project_root / "manuscript"
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
