"""Cheap text-analysis tools.

Wordcount uses the same heuristic as 备忘 13's reference code: count
non-whitespace code points. That's roughly the right figure for Chinese
prose, where each character ≈ 1 字; for mixed Chinese+English we still
get a serviceable estimate.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from writer.rag import ProjectRagIndex, format_hits
from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class Wordcount:
    """Estimate 字数 for a chunk of text or project file tree."""

    name = "wordcount"
    description = "统计文本或项目路径的粗略字数(剔除空白);适合中文小说草稿。"

    def run(
        self,
        runtime: ToolRuntime,
        *,
        text: str | None = None,
        path: str | None = None,
    ) -> ToolResult:
        if path is not None:
            target = runtime.safe_path(path)
            if target.is_dir():
                texts = [
                    file.read_text(encoding="utf-8")
                    for file in _iter_text_files(target)
                ]
                text = "\n".join(texts)
            else:
                text = target.read_text(encoding="utf-8")

        if text is None:
            text = ""

        stripped = text.replace("\n", "").replace(" ", "").replace("\t", "")
        chars = len(stripped)
        return ToolResult(
            output=str(chars),
            metadata={"chars": chars, "raw_len": len(text), "path": path},
        )


class ProjectSearch:
    """Search project text with exact matches plus project-level RAG."""

    name = "project_search"
    description = "在项目目录内搜索关键词;返回匹配文件、行号和片段。"

    def run(
        self,
        runtime: ToolRuntime,
        *,
        query: str,
        path: str = ".",
        limit: int = 20,
    ) -> ToolResult:
        keyword = query.strip()
        if not keyword:
            return ToolResult(output="请提供搜索关键词。", metadata={"matched": 0})

        target = runtime.safe_path(path)
        files = [target] if target.is_file() else list(_iter_text_files(target))
        exact_lines: list[str] = []

        for file in files:
            try:
                content = file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            for line_no, line in enumerate(content.splitlines(), start=1):
                if keyword not in line:
                    continue
                relative = file.relative_to(runtime.project_root)
                snippet = line.strip()
                exact_lines.append(f"{relative.as_posix()}:{line_no}: {snippet}")
                if len(exact_lines) >= limit:
                    output = "\n".join(exact_lines)
                    return ToolResult(
                        output=output,
                        truncated=True,
                        metadata={
                            "matched": len(exact_lines),
                            "query": keyword,
                            "rag_matched": 0,
                        },
                    )

        rag_hits = ProjectRagIndex(runtime.project_root).query(keyword, k=5)
        sections: list[str] = []
        if exact_lines:
            sections.append("关键词命中:\n" + "\n".join(exact_lines))
        if rag_hits:
            sections.append("RAG 召回:\n" + format_hits(rag_hits))
        output = "\n\n".join(sections) if sections else f"未找到关键词：{keyword}"
        return ToolResult(
            output=output,
            metadata={
                "matched": len(exact_lines),
                "query": keyword,
                "rag_matched": len(rag_hits),
            },
        )


def _iter_text_files(root: Path) -> list[Path]:
    suffixes = {".md", ".txt"}
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            files.append(path)
    return files


__all__ = ["ProjectSearch", "Wordcount"]
