"""Tests for the writer.tools layer.

Covers per 备忘 07 (path safety, capability gates) + per 备忘 13 (registry
shape, mock tools, langchain bridge).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

from writer.tools import (
    ChapterLocate,
    ForeshadowQuery,
    ProjectSearch,
    SafeListDir,
    SafeReadFile,
    ToolDeniedError,
    ToolNotADirectoryError,
    ToolNotFoundError,
    ToolRegistry,
    Wordcount,
    built_tool_registry,
    to_langchain_tools,
)
from writer.tools.runtime import ToolRuntime

# ---------------------------------------------------------------------------
# Runtime / path safety (per 备忘 07)
# ---------------------------------------------------------------------------


def test_safe_path_rejects_parent_traversal(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    with pytest.raises(ToolDeniedError):
        runtime.safe_path("../outside.txt")


def test_safe_path_rejects_absolute_outside_root(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    with pytest.raises(ToolDeniedError):
        runtime.safe_path("/etc/passwd")


def test_safe_path_accepts_relative_and_root(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    nested = tmp_path / "outline" / "premise.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("hi", encoding="utf-8")

    assert runtime.safe_path("outline/premise.md") == nested
    assert runtime.safe_path(str(nested)) == nested


def test_require_shell_denied_by_default(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    with pytest.raises(ToolDeniedError):
        runtime.require_shell()


# ---------------------------------------------------------------------------
# File IO tools
# ---------------------------------------------------------------------------


def test_safe_read_file_truncates_at_runtime_budget(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path, max_file_size=20)
    target = tmp_path / "big.md"
    target.write_text("x" * 100, encoding="utf-8")

    result = SafeReadFile().run(runtime, path="big.md")

    assert result.truncated is True
    assert "[内容已截断" in result.output
    assert result.metadata["original_size"] == 100


def test_safe_read_file_rejects_traversal(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    with pytest.raises(ToolDeniedError):
        SafeReadFile().run(runtime, path="../../../etc/passwd")


def test_safe_list_dir_skips_hidden(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    (tmp_path / "drafts").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "readme.md").write_text("hi", encoding="utf-8")

    result = SafeListDir().run(runtime, path=".")

    assert "drafts" in result.output
    assert "readme.md" in result.output
    assert ".git" not in result.output
    assert result.metadata["count"] == 2


def test_safe_list_dir_raises_tool_not_a_directory_on_file_path(tmp_path: Path) -> None:
    """When the target path resolves to a file, SafeListDir must raise ToolNotADirectoryError.

    Per arch-optimizer N2 (2026-07-05): before M7, ``SafeListDir`` raised
    stdlib ``NotADirectoryError``, which the engine's ``except ToolError``
    branch in ``_engine_loop`` could not catch — the error was
    misclassified as "engine boundary" rather than "tool error". This
    test pins the new contract: builtin tools raise the project's
    ``ToolError`` hierarchy so the engine can route them through a
    single funnel.
    """
    runtime = ToolRuntime(project_root=tmp_path)
    target = tmp_path / "not_a_dir.md"
    target.write_text("hi", encoding="utf-8")

    with pytest.raises(ToolNotADirectoryError):
        SafeListDir().run(runtime, path="not_a_dir.md")


# ---------------------------------------------------------------------------
# Analysis + project mocks
# ---------------------------------------------------------------------------


def test_wordcount_handles_chinese_with_whitespace() -> None:
    runtime = ToolRuntime(project_root=Path("/tmp"))
    # 8 Chinese chars; spaces + a newline must be stripped.
    result = Wordcount().run(runtime, text="废土 少年\n继承 一座")
    assert result.output == "8"
    assert result.metadata["chars"] == 8


def test_wordcount_can_count_project_path(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    (manuscript / "chapter-01.md").write_text("第一章\n\n少年 出门", encoding="utf-8")

    result = Wordcount().run(runtime, path="manuscript")

    assert result.output == "7"
    assert result.metadata["path"] == "manuscript"


def test_project_search_finds_keyword_inside_project(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    target = tmp_path / "outline" / "大纲.md"
    target.parent.mkdir()
    target.write_text("主角得到玉簪\n反派现身", encoding="utf-8")

    result = ProjectSearch().run(runtime, query="玉簪")

    assert "outline/大纲.md:1" in result.output
    assert result.metadata["matched"] == 1


def test_chapter_locate_returns_handle_json() -> None:
    runtime = ToolRuntime(project_root=Path("/tmp/proj").resolve())
    result = ChapterLocate().run(runtime, chapter="1.3")
    parsed = json.loads(result.output)
    assert parsed["chapter_id"] == "1.3"
    assert parsed["draft_path"].endswith("1.3_待实现.md")
    assert parsed["project_root"] == str(runtime.project_root)


def test_foreshadow_query_returns_mock_with_ids() -> None:
    runtime = ToolRuntime(project_root=Path("/tmp"))
    result = ForeshadowQuery().run(runtime, query="F003 玉簪来历")
    assert "F003" in result.output
    assert "F012" in result.output
    assert result.metadata["matched"] == ["F003", "F012"]


# ---------------------------------------------------------------------------
# Registry + LangChain bridge
# ---------------------------------------------------------------------------


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry(tools=[SafeReadFile()])
    with pytest.raises(ValueError):
        registry.register(SafeReadFile())


def test_registry_invoke_raises_on_unknown() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.invoke("nope", ToolRuntime(project_root=Path("/tmp")))


def test_built_tool_registry_includes_core_tools() -> None:
    registry = built_tool_registry()
    expected = {
        "safe_read_file",
        "safe_list_dir",
        "wordcount",
        "project_search",
        "chapter_locate",
        "foreshadow_query",
    }
    assert expected <= set(registry.names())


def test_langchain_bridge_returns_base_tools(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    registry = built_tool_registry()

    base_tools = to_langchain_tools(registry, runtime)

    assert len(base_tools) >= 5
    assert all(isinstance(t, BaseTool) for t in base_tools)

    target = tmp_path / "premise.md"
    target.write_text("hello", encoding="utf-8")
    read_tool = next(t for t in base_tools if t.name == "safe_read_file")
    assert read_tool.invoke({"path": "premise.md"}) == "hello"
