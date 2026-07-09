"""项目级伏笔 ledger（``伏笔.yaml``）与结构化查询辅助函数。

用确定性的进程内查询取代了旧的基于 RAG 的伏笔查找。Schema 见
``openspec/changes/chg-remove-rag/specs/foreshadow-ledger/spec.md``，
刻意做成人类可手编：作者应当可以手工维护 ledger，无需经过任何
LLM 或向量存储来回绕。

公开 API：

* :func:`load_ledger` —— 读取并校验 ledger；文件缺失时返回 ``[]``。
  文件存在但格式错乱时抛 :class:`ForeshadowLedgerSchemaError`
  （工具层捕获后产出友好的 ``ToolResult``）。
* :func:`query_ledger` —— 在条目列表上的纯过滤。所有参数使用
  **AND** 语义组合。
* :class:`ForeshadowLedgerSchemaError` —— 仅由 :func:`load_ledger`
  抛出的领域异常；工具层负责把它映射成不抛异常的 ``ToolResult``。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml

#: 项目级 ledger 文件名。中文文件名匹配项目既有约定
#: （参见 ``技术难点与解决方案备忘/``、``创意/核心创意.md``）。
LEDGER_FILENAME = "伏笔.yaml"

#: 每条 ledger 条目必须包含的字段。``paid_chapter`` 允许为 ``None``，
#: 表示「已埋伏但尚未回收」。
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"id", "tags", "status", "laid_chapter", "paid_chapter", "notes"}
)

#: ``status`` 字段允许的值。
_VALID_STATUS: frozenset[str] = frozenset({"laid", "paid"})

#: 规范 id 模式：``F`` 后跟一位或多位数字。仅用于人类友好校验；
#: ``query_ledger`` 不强制它。
_ID_PATTERN = re.compile(r"^F\d+$")


class ForeshadowLedgerSchemaError(Exception):
    """``伏笔.yaml`` 存在但不满足 schema 时抛出。

    :class:`ForeshadowSearch` 工具捕获该异常，并把它转换为
    ``metadata.error="schema"`` 的 ``ToolResult`` —— 异常本身永远
    不会从工具层逃逸。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_ledger(project_root: Path) -> list[dict[str, Any]]:
    """返回 ``project_root`` 解析后的 ledger。

    行为：

    * 文件缺失 → 返回 ``[]``（视为空 ledger 而非错误 —— 新项目
      允许暂时尚无伏笔）。
    * 文件存在但格式错乱 → 抛 :class:`ForeshadowLedgerSchemaError`。
      调用方（即工具层）必须处理该异常并返回友好的结果。
    """

    path = (project_root / LEDGER_FILENAME).resolve()
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ForeshadowLedgerSchemaError(
            f"伏笔 ledger YAML 解析失败: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ForeshadowLedgerSchemaError(
            "伏笔 ledger 格式不兼容（根节点必须是 mapping）"
        )
    if "foreshadows" not in data:
        raise ForeshadowLedgerSchemaError(
            "伏笔 ledger 格式不兼容（缺失 foreshadows 列表）"
        )
    foreshadows = data["foreshadows"]
    if not isinstance(foreshadows, list):
        raise ForeshadowLedgerSchemaError(
            "伏笔 ledger 格式不兼容（foreshadows 必须是列表）"
        )

    out: list[dict[str, Any]] = []
    for idx, entry in enumerate(foreshadows):
        if not isinstance(entry, dict):
            raise ForeshadowLedgerSchemaError(
                f"伏笔 ledger 第 {idx} 条不是 mapping"
            )
        missing = _REQUIRED_FIELDS - set(entry.keys())
        if missing:
            raise ForeshadowLedgerSchemaError(
                f"伏笔 ledger 第 {idx} 条缺字段: {sorted(missing)}"
            )
        out.append(entry)
    return out


def query_ledger(
    entries: list[dict[str, Any]],
    *,
    id: str | None = None,
    tags: list[str] | None = None,
    status: Literal["laid", "paid", "all"] = "all",
    chapter_range: tuple[int, int] | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    """用结构化条件过滤 ``entries``；所有过滤条件以 AND 组合。

    Args:
        id: 精确 ``F\\d+`` 查找。提供时仅返回 id 匹配的条目。
        tags: ANY 匹配。条目的 ``tags`` 至少有一个等于所给 tags
            之一时通过（本参数内为 OR 语义，跨参数为 AND 语义）。
            空列表是 no-op。
        status: 取值 ``"laid"`` / ``"paid"`` / ``"all"``。``"laid"``
            包含 ``paid_chapter is None`` 的条目；``"paid"`` 要求
            ``paid_chapter`` 为非空整数。
        chapter_range: ``(lo, hi)`` 对 ``laid_chapter`` 的闭区间。
        keyword: 对 ``id`` / ``tags`` 任一元素 / ``notes`` 的子串
            匹配。大小写敏感。

    本函数为纯函数：没有文件系统 IO，没有日志，不修改输入列表。
    """

    results = list(entries)

    if id is not None:
        results = [e for e in results if e.get("id") == id]

    if tags:
        results = [e for e in results if any(t in e.get("tags", []) for t in tags)]

    if status != "all":
        if status == "paid":
            results = [
                e for e in results
                if e.get("status") == "paid" and e.get("paid_chapter") is not None
            ]
        else:  # "laid"
            results = [e for e in results if e.get("status") == "laid"]

    if chapter_range is not None:
        lo, hi = chapter_range
        results = [
            e for e in results
            if isinstance(e.get("laid_chapter"), int) and lo <= e["laid_chapter"] <= hi
        ]

    if keyword:
        kw = keyword
        results = [
            e for e in results
            if kw in str(e.get("id", ""))
            or kw in (e.get("notes") or "")
            or any(kw in str(t) for t in e.get("tags", []))
        ]

    return results


__all__ = [
    "ForeshadowLedgerSchemaError",
    "LEDGER_FILENAME",
    "load_ledger",
    "query_ledger",
]
