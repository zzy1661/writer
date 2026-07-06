"""Foreshadow lookup backed by the project RAG index."""

from __future__ import annotations

from typing import TYPE_CHECKING

from writer.rag import ProjectRagIndex, format_hits
from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class ForeshadowQuery:
    """Look up 伏笔 entries that match a free-form query."""

    name = "foreshadow_query"
    description = (
        "查询项目资料中与 query 相关的伏笔、前文铺垫和回收线索。"
    )

    def run(self, runtime: ToolRuntime, *, query: str) -> ToolResult:
        hits = ProjectRagIndex(runtime.project_root).query(query, k=8)
        output = format_hits(hits)
        return ToolResult(
            output=output,
            metadata={
                "query": query,
                "matched": [hit.source for hit in hits],
                "rag_matched": len(hits),
            },
        )


__all__ = ["ForeshadowQuery"]
