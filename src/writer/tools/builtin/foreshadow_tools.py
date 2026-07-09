"""由 ``<project_root>/伏笔.yaml`` 支持的结构化伏笔查询。

取代了之前的基于 RAG 的 :class:`ForeshadowQuery`（per ``chg-remove-rag``）：
不再对项目树做模糊向量召回，而是读取一份确定性的 YAML ledger，
在内存中用结构化条件过滤。所有过滤条件以 AND 组合。

分层：
* 本模块负责工具层接线。
* 实际的 ledger IO 与过滤逻辑位于
  :mod:`writer.tools.builtin.foreshadow_ledger`，让未来的测试 / 工具
  可以在不引入 tool Protocol 的情况下 import 它们。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from writer.tools.builtin.foreshadow_ledger import (
    ForeshadowLedgerSchemaError,
    load_ledger,
    query_ledger,
)
from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime

#: :func:`writer.engine.deps.production_deps` 在未绑定项目（S0）时
#: 使用的哨兵 project_root。在此处镜像一份，避免把 engine 常量泄漏
#: 到无路径工具的 import 图中。
_NO_PROJECT_ROOT = "/__no_project__"


class ForeshadowSearch:
    """用结构化过滤条件查询项目 ``伏笔.yaml`` ledger。

    工具是**无路径**的：它自动在 ``<runtime.project_root>/伏笔.yaml``
    定位 ledger。当 ``runtime.project_root`` 为 S0 哨兵时，工具返回
    友好的结果而非尝试读取不存在的目录。
    """

    name = "foreshadow_search"
    description = (
        "查询项目伏笔 ledger（伏笔.yaml），支持按 ID、tag、status（laid/paid/all）、"
        "章节范围、关键字子串过滤。多条件同时给定时取交集（AND）。"
    )

    def run(
        self,
        runtime: ToolRuntime,
        *,
        id: str | None = None,
        tags: list[str] | None = None,
        status: Literal["laid", "paid", "all"] = "all",
        chapter_range: tuple[int, int] | None = None,
        keyword: str | None = None,
    ) -> ToolResult:
        # S0 路径：引擎用哨兵 project_root 创建了 ToolRuntime，
        # 但 ledger 显然不在那里。返回友好的错误结果，而不是让
        # FileNotFoundError 冒泡成 aborted 轮次。
        if str(runtime.project_root) == _NO_PROJECT_ROOT:
            return ToolResult(
                output="未绑定项目，无法查询伏笔 ledger。",
                metadata={"error": "no_project_root"},
            )

        try:
            entries = load_ledger(runtime.project_root)
        except ForeshadowLedgerSchemaError as exc:
            return ToolResult(
                output=f"伏笔 ledger 格式不兼容：{exc.message}",
                metadata={"error": "schema"},
            )

        if not entries:
            return ToolResult(
                output="暂无伏笔记录，请先创建 伏笔.yaml 或在 /init 时生成。",
                metadata={"matched": 0, "total": 0},
            )

        results = query_ledger(
            entries,
            id=id,
            tags=tags,
            status=status,
            chapter_range=chapter_range,
            keyword=keyword,
        )

        if not results:
            return ToolResult(
                output="未匹配到符合条件的伏笔。",
                metadata={
                    "matched": 0,
                    "total": len(entries),
                    "filters": _filters_dict(
                        id, tags, status, chapter_range, keyword
                    ),
                },
            )

        return ToolResult(
            output=_format_hits(results),
            metadata={
                "matched": len(results),
                "total": len(entries),
                "filters": _filters_dict(
                    id, tags, status, chapter_range, keyword
                ),
            },
        )


def _format_hits(hits: list[dict]) -> str:
    lines = []
    for h in hits:
        entry_id = str(h.get("id", "?"))
        tags = h.get("tags") or []
        tags_str = ",".join(str(t) for t in tags)
        status = str(h.get("status", "?"))
        laid = h.get("laid_chapter", "?")
        paid = h.get("paid_chapter")
        paid_str = f"ch{paid}" if paid is not None else "未回收"
        notes = str(h.get("notes") or "")
        lines.append(
            f"- {entry_id} [{tags_str}] status={status} "
            f"laid=ch{laid} paid={paid_str} | {notes}"
        )
    return "\n".join(lines)


def _filters_dict(
    id: str | None,
    tags: list[str] | None,
    status: str,
    chapter_range: tuple[int, int] | None,
    keyword: str | None,
) -> dict[str, object]:
    return {
        "id": id,
        "tags": tags,
        "status": status,
        "chapter_range": chapter_range,
        "keyword": keyword,
    }


__all__ = ["ForeshadowSearch"]
