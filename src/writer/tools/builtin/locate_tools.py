"""Project-aware chapter locator.

S0 stub: identifies the requested chapter by id and returns a structured
handle. The real locator (per 备忘 02 + 04) will parse ``outline/`` +
``manuscript/`` and return paths verified against ``project_root``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class ChapterLocate:
    """Resolve a chapter alias into a structured handle."""

    name = "chapter_locate"
    description = (
        '把 "1.3"、"卷一第三章" 或章节标题解析为标准章节句柄,'
        "返回 chapter_id / title / draft_path。"
    )

    def run(
        self, runtime: ToolRuntime, *, chapter: str | None = None
    ) -> ToolResult:
        if chapter is None:
            chapter = "1.1"

        # S0 mock: echo the request rather than parse the real outline.
        # Real implementation will read outline/toc.md via safe_read_file.
        handle = {
            "chapter_id": chapter,
            "title": "待实现",
            "draft_path": f"manuscript/{chapter}_待实现.md",
            "project_root": str(runtime.project_root),
        }
        return ToolResult(output=json.dumps(handle, ensure_ascii=False), metadata=handle)


__all__ = ["ChapterLocate"]
