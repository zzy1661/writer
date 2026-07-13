"""项目感知的章节定位器。

S0 stub：按 id 识别所请求的章节并返回结构化句柄。真正的定位器
（per 备忘 02 + 04）将解析 ``大纲/`` + ``草稿/`` 并返回
经过 ``project_root`` 校验的路径。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class ChapterLocate:
    """把章节别名解析为结构化句柄。"""

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

        # S0 mock：回显请求而非真正解析大纲。
        # 真正的实现会通过 safe_read_file 读取 大纲/章节目录.md。
        handle = {
            "chapter_id": chapter,
            "title": "待实现",
            "draft_path": f"草稿/{chapter}_待实现.md",
            "project_root": str(runtime.project_root),
        }
        return ToolResult(output=json.dumps(handle, ensure_ascii=False), metadata=handle)


__all__ = ["ChapterLocate"]
