"""Tests for the foreshadow ledger module + ``ForeshadowSearch`` tool.

Covers all scenarios in
``openspec/changes/chg-remove-rag/specs/foreshadow-ledger/spec.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from writer.tools.builtin.foreshadow_ledger import (
    LEDGER_FILENAME,
    ForeshadowLedgerSchemaError,
    load_ledger,
    query_ledger,
)
from writer.tools.builtin.foreshadow_tools import ForeshadowSearch
from writer.tools.runtime import ToolRuntime

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


def _sample_entries() -> list[dict]:
    return [
        {
            "id": "F001",
            "tags": ["玉簪", "旧匣子", "身世"],
            "status": "paid",
            "laid_chapter": 3,
            "paid_chapter": 47,
            "notes": "主角身世揭晓",
        },
        {
            "id": "F002",
            "tags": ["反派", "卧底"],
            "status": "laid",
            "laid_chapter": 12,
            "paid_chapter": None,
            "notes": "反派 A 真实身份",
        },
        {
            "id": "F003",
            "tags": ["玉簪", "匣子"],
            "status": "laid",
            "laid_chapter": 8,
            "paid_chapter": None,
            "notes": "匣子夹层里藏了玉簪",
        },
        {
            "id": "F004",
            "tags": ["感情线"],
            "status": "paid",
            "laid_chapter": 15,
            "paid_chapter": 30,
            "notes": "主角与配角感情确认",
        },
    ]


# ---------------------------------------------------------------------------
# load_ledger: file-level behavior
# ---------------------------------------------------------------------------


def test_load_ledger_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_ledger(tmp_path) == []


def test_load_ledger_empty_foreshadows_returns_empty(tmp_path: Path) -> None:
    (tmp_path / LEDGER_FILENAME).write_text("foreshadows: []\n", encoding="utf-8")
    assert load_ledger(tmp_path) == []


def test_load_ledger_valid_file_returns_entries(tmp_path: Path) -> None:
    (tmp_path / LEDGER_FILENAME).write_text(
        "foreshadows:\n  - id: F001\n    tags: [玉簪]\n    status: paid\n"
        "    laid_chapter: 3\n    paid_chapter: 47\n    notes: x\n",
        encoding="utf-8",
    )
    entries = load_ledger(tmp_path)
    assert len(entries) == 1
    assert entries[0]["id"] == "F001"


def test_load_ledger_missing_foreshadows_key_raises(tmp_path: Path) -> None:
    (tmp_path / LEDGER_FILENAME).write_text("other: 1\n", encoding="utf-8")
    with pytest.raises(ForeshadowLedgerSchemaError, match="foreshadows"):
        load_ledger(tmp_path)


def test_load_ledger_foreshadows_not_list_raises(tmp_path: Path) -> None:
    (tmp_path / LEDGER_FILENAME).write_text("foreshadows: oops\n", encoding="utf-8")
    with pytest.raises(ForeshadowLedgerSchemaError):
        load_ledger(tmp_path)


def test_load_ledger_entry_missing_field_raises(tmp_path: Path) -> None:
    (tmp_path / LEDGER_FILENAME).write_text(
        "foreshadows:\n  - id: F001\n    tags: []\n", encoding="utf-8"
    )
    with pytest.raises(ForeshadowLedgerSchemaError, match="缺字段"):
        load_ledger(tmp_path)


def test_load_ledger_invalid_yaml_raises(tmp_path: Path) -> None:
    (tmp_path / LEDGER_FILENAME).write_text(":\n  - :\nbroken", encoding="utf-8")
    with pytest.raises(ForeshadowLedgerSchemaError, match="YAML"):
        load_ledger(tmp_path)


# ---------------------------------------------------------------------------
# query_ledger: filter semantics
# ---------------------------------------------------------------------------


def test_query_ledger_lookup_by_id() -> None:
    results = query_ledger(_sample_entries(), id="F003")
    assert len(results) == 1
    assert results[0]["id"] == "F003"


def test_query_ledger_status_laid_excludes_paid() -> None:
    results = query_ledger(_sample_entries(), status="laid")
    ids = {e["id"] for e in results}
    assert ids == {"F002", "F003"}


def test_query_ledger_status_paid_excludes_laid() -> None:
    results = query_ledger(_sample_entries(), status="paid")
    ids = {e["id"] for e in results}
    assert ids == {"F001", "F004"}


def test_query_ledger_status_all_returns_everything() -> None:
    results = query_ledger(_sample_entries(), status="all")
    assert len(results) == 4


def test_query_ledger_tag_match_any_of() -> None:
    results = query_ledger(_sample_entries(), tags=["玉簪", "感情线"])
    ids = {e["id"] for e in results}
    # F001 has 玉簪, F003 has 玉簪, F004 has 感情线
    assert ids == {"F001", "F003", "F004"}


def test_query_ledger_chapter_range_filters_laid_chapter() -> None:
    results = query_ledger(_sample_entries(), chapter_range=(10, 20))
    ids = {e["id"] for e in results}
    # F002 laid=12, F004 laid=15 are in range
    assert ids == {"F002", "F004"}


def test_query_ledger_keyword_matches_id() -> None:
    results = query_ledger(_sample_entries(), keyword="F003")
    assert len(results) == 1
    assert results[0]["id"] == "F003"


def test_query_ledger_keyword_matches_tag() -> None:
    results = query_ledger(_sample_entries(), keyword="玉簪")
    ids = {e["id"] for e in results}
    assert ids == {"F001", "F003"}


def test_query_ledger_keyword_matches_notes() -> None:
    results = query_ledger(_sample_entries(), keyword="真实身份")
    assert len(results) == 1
    assert results[0]["id"] == "F002"


def test_query_ledger_multiple_filters_combine_with_and() -> None:
    # tags=玉簪 narrows to F001 / F003; status=laid further narrows to F003
    results = query_ledger(
        _sample_entries(), tags=["玉簪"], status="laid"
    )
    assert len(results) == 1
    assert results[0]["id"] == "F003"


def test_query_ledger_does_not_mutate_input() -> None:
    entries = _sample_entries()
    snapshot = list(entries)
    query_ledger(entries, status="laid")
    assert entries == snapshot


# ---------------------------------------------------------------------------
# ForeshadowSearch tool: end-to-end
# ---------------------------------------------------------------------------


def _write_ledger(project_root: Path, content: str) -> None:
    (project_root / LEDGER_FILENAME).write_text(content, encoding="utf-8")


_VALID_LEDGER = """
foreshadows:
  - id: F001
    tags: [玉簪, 旧匣子]
    status: paid
    laid_chapter: 3
    paid_chapter: 47
    notes: 主角身世揭晓
  - id: F002
    tags: [反派, 卧底]
    status: laid
    laid_chapter: 12
    paid_chapter: null
    notes: 反派 A 真实身份
"""


def test_foreshadow_search_missing_file_returns_friendly_message(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, keyword="F001")
    assert "暂无伏笔" in result.output
    assert result.metadata.get("matched") == 0


def test_foreshadow_search_empty_ledger_returns_friendly_message(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "foreshadows: []\n")
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, keyword="F001")
    assert "暂无伏笔" in result.output
    assert result.metadata.get("matched") == 0


def test_foreshadow_search_schema_invalid_returns_error_result(tmp_path: Path) -> None:
    _write_ledger(tmp_path, "foreshadows: oops\n")
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, keyword="F001")
    assert "格式不兼容" in result.output
    assert result.metadata.get("error") == "schema"


def test_foreshadow_search_lookup_by_id(tmp_path: Path) -> None:
    _write_ledger(tmp_path, _VALID_LEDGER)
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, id="F001")
    assert "F001" in result.output
    assert result.metadata["matched"] == 1


def test_foreshadow_search_status_laid_excludes_paid(tmp_path: Path) -> None:
    _write_ledger(tmp_path, _VALID_LEDGER)
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, status="laid")
    assert "F002" in result.output
    assert "F001" not in result.output
    assert result.metadata["matched"] == 1


def test_foreshadow_search_tag_filter(tmp_path: Path) -> None:
    _write_ledger(tmp_path, _VALID_LEDGER)
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, tags=["玉簪"])
    assert "F001" in result.output
    assert "F002" not in result.output
    assert result.metadata["matched"] == 1


def test_foreshadow_search_keyword_substring_match(tmp_path: Path) -> None:
    _write_ledger(tmp_path, _VALID_LEDGER)
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, keyword="玉簪")
    assert "F001" in result.output


def test_foreshadow_search_multiple_filters_and_combine(tmp_path: Path) -> None:
    _write_ledger(tmp_path, _VALID_LEDGER)
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(
        runtime, tags=["玉簪"], status="paid"
    )
    assert "F001" in result.output
    assert result.metadata["matched"] == 1


def test_foreshadow_search_no_match_returns_friendly_output(tmp_path: Path) -> None:
    _write_ledger(tmp_path, _VALID_LEDGER)
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, id="F999")
    assert "未匹配到" in result.output
    assert result.metadata["matched"] == 0
    assert result.metadata["total"] == 2


def test_foreshadow_search_sentinel_project_root_returns_error() -> None:
    """S0 path: no project bound. The tool MUST NOT attempt to read."""
    runtime = ToolRuntime(project_root=Path("/__no_project__"))
    result = ForeshadowSearch().run(runtime, id="F001")
    assert "未绑定项目" in result.output
    assert result.metadata["error"] == "no_project_root"


def test_foreshadow_search_built_in_registry_includes_search() -> None:
    from writer.tools.builtin import built_tool_registry

    registry = built_tool_registry()
    assert "foreshadow_search" in registry.names()
    assert "foreshadow_query" not in registry.names()
