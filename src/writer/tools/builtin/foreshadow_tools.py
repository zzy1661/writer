"""Mock 伏笔 library queries.

The real implementation (per 备忘 10) will index the 伏笔 workbook via
the RAG store. For now, ``ForeshadowQuery`` returns a deterministic stub
so callers can exercise the engine's ``call_tool`` branch end-to-end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class ForeshadowQuery:
    """Look up 伏笔 entries that match a free-form query."""

    name = "foreshadow_query"
    description = (
        "查询伏笔库中与 query 相关的条目;MVP 返回 mock 数据,"
        "未来由 RAG 索引 (per 备忘 10 + 12) 提供真实结果。"
    )

    def run(self, runtime: ToolRuntime, *, query: str) -> ToolResult:
        # Deterministic mock — keep the same shape the real pipeline
        # will produce, so downstream parsers stay stable.
        return ToolResult(
            output=(
                f"[mock] 与 {query!r} 相关的伏笔:\n"
                "- F003 玉簪真实来历 | 状态=潜伏 | 计划第 18 章回收\n"
                "- F012 地窖暗门钥匙 | 状态=触发中 | 计划第 24 章收束\n"
            ),
            metadata={"query": query, "matched": ["F003", "F012"]},
        )


__all__ = ["ForeshadowQuery"]
