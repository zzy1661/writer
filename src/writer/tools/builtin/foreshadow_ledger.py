"""Project-local foreshadow ledger (伏笔.yaml) and structured query helpers.

Replaces the old RAG-based foreshadow lookup with a deterministic
in-process query against a YAML ledger. The schema is documented in
``openspec/changes/chg-remove-rag/specs/foreshadow-ledger/spec.md`` and
intentionally human-editable: a writer should be able to maintain the
ledger by hand without round-tripping through any LLM or vector store.

Public surface:

* :func:`load_ledger` — read & validate the ledger; returns ``[]`` on
  missing file. Raises :class:`ForeshadowLedgerSchemaError` on a
  present-but-malformed file (the tool layer catches this and produces
  a friendly ``ToolResult``).
* :func:`query_ledger` — pure filter on a list of entries. All
  arguments combine with **AND** semantics.
* :class:`ForeshadowLedgerSchemaError` — domain exception surfaced from
  :func:`load_ledger` only; the tool layer is responsible for mapping
  it to a non-raising ``ToolResult``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml

#: Filename of the project-local ledger. Chinese filename chosen to match
#: the project's existing convention (cf. ``技术难点与解决方案备忘/``,
#: ``创意/核心创意.md``).
LEDGER_FILENAME = "伏笔.yaml"

#: Fields every ledger entry MUST contain. ``paid_chapter`` is allowed
#: to be ``None`` to indicate "laid but not yet paid off".
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"id", "tags", "status", "laid_chapter", "paid_chapter", "notes"}
)

#: Permitted values for the ``status`` field.
_VALID_STATUS: frozenset[str] = frozenset({"laid", "paid"})

#: Canonical id pattern: ``F`` followed by one or more digits. Used only
#: for human-friendly validation; ``query_ledger`` does not enforce it.
_ID_PATTERN = re.compile(r"^F\d+$")


class ForeshadowLedgerSchemaError(Exception):
    """Raised when ``伏笔.yaml`` exists but does not satisfy the schema.

    The :class:`ForeshadowSearch` tool catches this and converts it to
    a ``ToolResult`` with ``metadata.error="schema"`` — the exception
    itself never escapes the tool layer.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_ledger(project_root: Path) -> list[dict[str, Any]]:
    """Return the parsed ledger for ``project_root``.

    Behavior:

    * File missing → return ``[]`` (treated as an empty ledger, not an
      error — a fresh project is allowed to have no foreshadows yet).
    * File present but malformed → raise
      :class:`ForeshadowLedgerSchemaError`. Callers (i.e. the tool
      layer) MUST handle the exception and return a friendly result.
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
    """Filter ``entries`` with structured criteria; all filters combine with AND.

    Args:
        id: Exact ``F\\d+`` lookup. When provided, only the entry with the
            matching ``id`` is returned.
        tags: ANY-of match. The entry passes if at least one of its
            ``tags`` equals one of the given tags (OR semantics within
            this argument, AND across arguments). Empty list is a no-op.
        status: One of ``"laid"`` / ``"paid"`` / ``"all"``. ``"laid"``
            includes entries with ``paid_chapter is None``; ``"paid"``
            requires ``paid_chapter`` to be a non-null integer.
        chapter_range: ``(lo, hi)`` inclusive bounds on ``laid_chapter``.
        keyword: Substring match against ``id`` / any element of
            ``tags`` / ``notes``. Case-sensitive.

    The function is pure: no filesystem IO, no logging, no mutation
    of the input list.
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
