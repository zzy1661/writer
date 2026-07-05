"""Cheap text-analysis tools.

Wordcount uses the same heuristic as 备忘 13's reference code: count
non-whitespace code points. That's roughly the right figure for Chinese
prose, where each character ≈ 1 字; for mixed Chinese+English we still
get a serviceable estimate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class Wordcount:
    """Estimate 字数 for a chunk of text."""

    name = "wordcount"
    description = "统计文本的粗略字数(剔除空白);适合中文小说草稿。"

    def run(self, runtime: ToolRuntime, *, text: str) -> ToolResult:
        stripped = text.replace("\n", "").replace(" ", "").replace("\t", "")
        chars = len(stripped)
        return ToolResult(
            output=str(chars),
            metadata={"chars": chars, "raw_len": len(text)},
        )


__all__ = ["Wordcount"]
