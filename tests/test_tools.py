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
    ForeshadowSearch,
    ProjectSearch,
    SafeEditFile,
    SafeGlob,
    SafeListDir,
    SafeReadFile,
    SafeWriteFile,
    ToolDeniedError,
    ToolNotADirectoryError,
    ToolNotFoundError,
    ToolOutputTooLargeError,
    ToolRegistry,
    Wordcount,
    built_tool_registry,
    to_langchain_tools,
)
from writer.tools.runtime import DEFAULT_WRITE_WHITELIST, ToolRuntime

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


def test_wordcount_returns_io_error_on_permission_denied(tmp_path: Path) -> None:
    """An unreadable path must surface as a ToolResult, not an unhandled exception.

    Per arch-optimizer M6 (2026-07-07): previously, a path under
    project_root that the OS refused to read would bubble out of
    ``Wordcount.run`` as ``PermissionError`` (or ``OSError``), hit
    the engine's generic ``except Exception`` arm, and surface as
    a generic ``ErrorEvent`` with no project context. The fix
    catches both and returns a ToolResult carrying the I/O error.
    """
    import stat

    runtime = ToolRuntime(project_root=tmp_path)
    locked = tmp_path / "locked.md"
    locked.write_text("看不见", encoding="utf-8")
    # Strip all permissions — Wordcount's ``read_text`` will raise
    # ``PermissionError`` (POSIX) or ``OSError`` (Windows fallback).
    locked.chmod(0)
    try:
        result = Wordcount().run(runtime, path="locked.md")
        assert result.output.startswith("读取失败")
        assert result.metadata["path"] == "locked.md"
        assert result.metadata["error"] == "io"
    finally:
        # Restore so pytest's tmp_path cleanup can delete the tree.
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)


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


def test_foreshadow_search_returns_friendly_message_without_ledger(tmp_path: Path) -> None:
    """No 伏笔.yaml → '暂无伏笔' message; no exception, no RAG recall."""
    runtime = ToolRuntime(project_root=tmp_path)
    result = ForeshadowSearch().run(runtime, keyword="F003")
    assert "暂无伏笔" in result.output
    assert result.metadata.get("matched") == 0


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
        "safe_write_file",
        "safe_edit_file",
        "safe_glob",
        "wordcount",
        "project_search",
        "chapter_locate",
        "foreshadow_search",
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


# ---------------------------------------------------------------------------
# SafeWriteFile (per chg-add-write-edit-glob D1-D4)
# ---------------------------------------------------------------------------


def _seed_manuscript(tmp_path: Path) -> tuple[ToolRuntime, Path]:
    """Return a runtime whose project_root has a manuscript/ directory."""

    (tmp_path / "manuscript").mkdir(parents=True, exist_ok=True)
    return ToolRuntime(project_root=tmp_path), tmp_path / "manuscript"


def test_safe_write_file_creates_new_file(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)

    result = SafeWriteFile().run(runtime, path="manuscript/ch1.md", content="hello\n")

    assert result.metadata["mode"] == "create"
    assert (ms_dir / "ch1.md").read_text(encoding="utf-8") == "hello\n"
    assert "backup_path" not in result.metadata  # create has no prior file to back up


def test_safe_write_file_create_mode_refuses_existing(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("original", encoding="utf-8")

    with pytest.raises(ToolDeniedError):
        SafeWriteFile().run(runtime, path="manuscript/ch1.md", content="new")

    # Original file unchanged
    assert (ms_dir / "ch1.md").read_text(encoding="utf-8") == "original"


def test_safe_write_file_overwrite_creates_backup(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("original", encoding="utf-8")

    result = SafeWriteFile().run(
        runtime, path="manuscript/ch1.md", content="new", mode="overwrite"
    )

    assert result.metadata["mode"] == "overwrite"
    assert (ms_dir / "ch1.md").read_text(encoding="utf-8") == "new"
    backup = Path(result.metadata["backup_path"])
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "original"


def test_safe_write_file_overwrite_no_backup_when_disabled(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("original", encoding="utf-8")

    result = SafeWriteFile().run(
        runtime,
        path="manuscript/ch1.md",
        content="new",
        mode="overwrite",
        backup=False,
    )

    assert "backup_path" not in result.metadata
    assert not list((tmp_path / ".writer" / "backups").rglob("ch1.md.*"))


def test_safe_write_file_append_skips_backup_and_atomic(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("line1\n", encoding="utf-8")

    result = SafeWriteFile().run(
        runtime,
        path="manuscript/ch1.md",
        content="line2\n",
        mode="append",
    )

    assert result.metadata["mode"] == "append"
    assert (ms_dir / "ch1.md").read_text(encoding="utf-8") == "line1\nline2\n"
    assert "backup_path" not in result.metadata
    # No tmp leftovers
    assert not list((ms_dir).glob("ch1.md.tmp.*"))


def test_safe_write_file_rejects_outside_whitelist(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)

    with pytest.raises(ToolDeniedError):
        SafeWriteFile().run(runtime, path="secrets/api_key.txt", content="x")

    # Even an existing file outside whitelist stays untouched
    outside = tmp_path.parent / "tmp_outside.txt"
    outside.write_text("orig", encoding="utf-8")
    try:
        with pytest.raises(ToolDeniedError):
            SafeWriteFile().run(runtime, path=str(outside), content="x")
        assert outside.read_text(encoding="utf-8") == "orig"
    finally:
        outside.unlink(missing_ok=True)


def test_whitelist_matches_subpath(tmp_path: Path) -> None:
    """Bug 4: `.writer/cache/*` 写入应被允许（祖先路径在白名单内）。"""
    runtime = ToolRuntime(project_root=tmp_path)

    result = SafeWriteFile().run(
        runtime, path=".writer/cache/foo.md", content="hi"
    )

    assert result.metadata["mode"] == "create"
    assert (tmp_path / ".writer" / "cache" / "foo.md").read_text(
        encoding="utf-8"
    ) == "hi"


def test_whitelist_matches_deep_subpath(tmp_path: Path) -> None:
    """Bug 4: `manuscript/<nested>/chapter.md` 写入应被允许。"""
    runtime = ToolRuntime(project_root=tmp_path)

    SafeWriteFile().run(
        runtime, path="manuscript/novel1/chapter.md", content="deep"
    )

    assert (tmp_path / "manuscript" / "novel1" / "chapter.md").read_text(
        encoding="utf-8"
    ) == "deep"


def test_whitelist_matches_agents_subpath(tmp_path: Path) -> None:
    """Bug 4: `.writer/agents/<name>.md` 写入应被允许。"""
    runtime = ToolRuntime(project_root=tmp_path)

    SafeWriteFile().run(
        runtime, path=".writer/agents/历史.md", content="agent body"
    )

    assert (tmp_path / ".writer" / "agents" / "历史.md").read_text(
        encoding="utf-8"
    ) == "agent body"


def test_whitelist_rejects_unrelated_subpath(tmp_path: Path) -> None:
    """Bug 4: 与白名单不相关的子路径仍应被拒绝。"""
    runtime = ToolRuntime(project_root=tmp_path)

    with pytest.raises(ToolDeniedError, match="白名单"):
        SafeWriteFile().run(runtime, path="secrets/api_key", content="x")


def test_whitelist_rejects_root_only(tmp_path: Path) -> None:
    """Bug 4: `AGENT.md` 走 `_guard_agent_md` 旁路,白名单检查不触发拒绝。"""
    runtime = ToolRuntime(project_root=tmp_path)
    (tmp_path / "manuscript").mkdir()

    # AGENT.md 写入需要 ## 当前状态 段
    content = "# Project\n\n## 当前状态\n\n- state: S0\n"
    result = SafeWriteFile().run(
        runtime, path="AGENT.md", content=content, mode="overwrite"
    )

    assert result.metadata["mode"] == "overwrite"
    assert (tmp_path / "AGENT.md").exists()


def test_safe_write_file_rejects_oversize_content(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path, max_file_size=10)
    (tmp_path / "manuscript").mkdir()

    with pytest.raises(ToolOutputTooLargeError):
        SafeWriteFile().run(
            runtime,
            path="manuscript/big.md",
            content="x" * 100,
        )


# ---------------------------------------------------------------------------
# AGENT.md guard (per chg-add-write-edit-glob D4)
# ---------------------------------------------------------------------------


def test_safe_write_file_rejects_agent_md_with_mode_create(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)

    with pytest.raises(ToolDeniedError, match="AGENT.md"):
        SafeWriteFile().run(
            runtime,
            path="AGENT.md",
            content="# x\n\n## 当前状态\n\n- state: S0\n",
            mode="create",
        )


def test_safe_write_file_rejects_agent_md_with_mode_append(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    (tmp_path / "AGENT.md").write_text(
        "# x\n\n## 当前状态\n\n- state: S0\n", encoding="utf-8"
    )

    with pytest.raises(ToolDeniedError, match="AGENT.md"):
        SafeWriteFile().run(
            runtime,
            path="AGENT.md",
            content="## 补丁\n",
            mode="append",
        )


def test_safe_write_file_agent_md_must_have_current_state_section(
    tmp_path: Path,
) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    (tmp_path / "AGENT.md").write_text(
        "# existing\n\n## 当前状态\n\n- state: S0\n", encoding="utf-8"
    )

    with pytest.raises(ToolDeniedError, match="## 当前状态"):
        SafeWriteFile().run(
            runtime,
            path="AGENT.md",
            content="# 全新内容（无状态段）\n",
            mode="overwrite",
        )


def test_safe_write_file_agent_md_preserves_genre_when_missing(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    (tmp_path / "AGENT.md").write_text(
        "# novel\n\n## 当前状态\n\n- state: S2\n- 题材: 历史\n\n## 其他\n",
        encoding="utf-8",
    )

    result = SafeWriteFile().run(
        runtime,
        path="AGENT.md",
        content="# novel\n\n## 当前状态\n\n- state: S3\n\n## 其他\n",
        mode="overwrite",
    )

    assert result.metadata.get("genre_guard_triggered") is True
    assert result.metadata.get("preserved_genre") == "历史"
    new_content = (tmp_path / "AGENT.md").read_text(encoding="utf-8")
    assert "- 题材: 历史" in new_content


# ---------------------------------------------------------------------------
# SafeEditFile (per chg-add-write-edit-glob D5)
# ---------------------------------------------------------------------------


def test_safe_edit_file_replaces_unique_match(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("hello world", encoding="utf-8")

    result = SafeEditFile().run(
        runtime,
        path="manuscript/ch1.md",
        old_string="world",
        new_string="earth",
    )

    assert result.metadata["replace_count"] == 1
    assert (ms_dir / "ch1.md").read_text(encoding="utf-8") == "hello earth"


def test_safe_edit_file_replace_all_when_multiple_matches(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("foo foo foo", encoding="utf-8")

    result = SafeEditFile().run(
        runtime,
        path="manuscript/ch1.md",
        old_string="foo",
        new_string="bar",
        replace_all=True,
    )

    assert result.metadata["replace_count"] == 3
    assert (ms_dir / "ch1.md").read_text(encoding="utf-8") == "bar bar bar"


def test_safe_edit_file_raises_when_old_string_ambiguous(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("foo foo foo", encoding="utf-8")

    with pytest.raises(ToolDeniedError, match="3"):
        SafeEditFile().run(
            runtime,
            path="manuscript/ch1.md",
            old_string="foo",
            new_string="bar",
            replace_all=False,
        )


def test_safe_edit_file_raises_when_old_string_missing(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("hello world", encoding="utf-8")

    with pytest.raises(ToolDeniedError, match="未找到"):
        SafeEditFile().run(
            runtime,
            path="manuscript/ch1.md",
            old_string="missing",
            new_string="new",
        )


def test_safe_edit_file_dry_run_returns_diff_no_write(tmp_path: Path) -> None:
    runtime, ms_dir = _seed_manuscript(tmp_path)
    (ms_dir / "ch1.md").write_text("hello world", encoding="utf-8")

    result = SafeEditFile().run(
        runtime,
        path="manuscript/ch1.md",
        old_string="world",
        new_string="earth",
        dry_run=True,
    )

    assert result.metadata["dry_run"] is True
    assert result.metadata["diff"]  # non-empty unified diff
    # File on disk unchanged
    assert (ms_dir / "ch1.md").read_text(encoding="utf-8") == "hello world"


# ---------------------------------------------------------------------------
# SafeGlob (per chg-add-write-edit-glob D6)
# ---------------------------------------------------------------------------


def test_safe_glob_matches_md_recursively(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("b", encoding="utf-8")

    runtime = ToolRuntime(project_root=tmp_path)
    result = SafeGlob().run(runtime, pattern="**/*.md")

    assert result.metadata["count"] == 2
    assert set(result.metadata["paths"]) == {"a.md", "sub/b.md"}


def test_safe_glob_top_level_only(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("b", encoding="utf-8")

    runtime = ToolRuntime(project_root=tmp_path)
    result = SafeGlob().run(runtime, pattern="*.md")

    assert result.metadata["count"] == 1
    assert result.metadata["paths"] == ["a.md"]


def test_safe_glob_skips_hidden(tmp_path: Path) -> None:
    (tmp_path / ".hidden").write_text("h", encoding="utf-8")
    (tmp_path / "visible.md").write_text("v", encoding="utf-8")

    runtime = ToolRuntime(project_root=tmp_path)
    result = SafeGlob().run(runtime, pattern="*")

    assert "visible.md" in result.metadata["paths"]
    assert ".hidden" not in result.metadata["paths"]


def test_safe_glob_sort_by_mtime_returns_newest_first(tmp_path: Path) -> None:
    import os
    import time

    old = tmp_path / "manuscript" / "ch1.md"
    new = tmp_path / "manuscript" / "ch2.md"
    old.parent.mkdir()
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    # Force mtime difference (avoid filesystem timestamp granularity)
    t = time.time()
    os.utime(old, (t - 100, t - 100))
    os.utime(new, (t, t))

    runtime = ToolRuntime(project_root=tmp_path)
    result = SafeGlob().run(
        runtime, pattern="manuscript/*.md", sort_by="mtime"
    )

    assert result.metadata["paths"] == ["manuscript/ch2.md", "manuscript/ch1.md"]


# ---------------------------------------------------------------------------
# ToolRuntime.allowed_write_paths (per chg-add-write-edit-glob D7)
# ---------------------------------------------------------------------------


def test_runtime_default_whitelist_when_none(tmp_path: Path) -> None:
    runtime = ToolRuntime(project_root=tmp_path)
    assert runtime.allowed_write_paths == DEFAULT_WRITE_WHITELIST


def test_runtime_default_whitelist_includes_dot_writer_cache(tmp_path: Path) -> None:
    """Bug 4: 验证默认白名单字面含 `.writer/cache` 与 `.writer/agents`(8 项)。"""
    assert ".writer/cache" in DEFAULT_WRITE_WHITELIST
    assert ".writer/agents" in DEFAULT_WRITE_WHITELIST
    assert len(DEFAULT_WRITE_WHITELIST) == 8


def test_runtime_explicit_frozenset_preserved(tmp_path: Path) -> None:
    runtime = ToolRuntime(
        project_root=tmp_path, allowed_write_paths=frozenset({"custom"})
    )
    assert runtime.allowed_write_paths == frozenset({"custom"})


def test_empty_whitelist_blocks_all_writes(tmp_path: Path) -> None:
    runtime = ToolRuntime(
        project_root=tmp_path, allowed_write_paths=frozenset()
    )
    (tmp_path / "manuscript").mkdir()

    with pytest.raises(ToolDeniedError):
        SafeWriteFile().run(
            runtime, path="manuscript/x.md", content="y"
        )
