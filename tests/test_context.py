"""Tests for the context pack assembly (per ``chg-remove-rag``).

These tests used to live in ``tests/test_context_rag.py`` and assert
RAG-style fuzzy recall (``ProjectRagIndex.query``). The RAG layer was
removed in ``chg-remove-rag`` because the placeholder ``HashEmbeddings``
had near-zero recall on real Chinese queries; the canon block now
composes layers from real project files (outline, characters,
``chapter_summaries.json``, last chapter). These tests pin the new
shape so future regressions show up here.
"""

from __future__ import annotations

from pathlib import Path

from writer.context import prep_context, trim_to_budget


def test_prep_context_builds_token_audit_and_trims(tmp_path: Path) -> None:
    outline = tmp_path / "outline" / "大纲.md"
    outline.parent.mkdir()
    outline.write_text("主角在第一章得到玉簪。" * 200, encoding="utf-8")

    pack = prep_context("1.2", "写玉簪线索", project_root=tmp_path, max_tokens=120)

    assert pack.system_block
    assert "写玉簪线索" in pack.task_block
    assert pack.token_audit["total"] <= 120
    assert set(pack.token_audit) >= {
        "system_block",
        "canon_block",
        "history_block",
        "task_block",
        "total",
        "budget",
    }


def test_trim_to_budget_prefers_system_task_then_canon() -> None:
    pack = prep_context("1.1", "任务", project_root=None, max_tokens=200)
    trimmed = trim_to_budget(pack, max_tokens=20)

    assert trimmed.system_block
    assert trimmed.task_block
    assert trimmed.token_audit["total"] <= 20


def test_canon_block_includes_outline_characters_summaries_and_last_chapter(
    tmp_path: Path,
) -> None:
    """Per chg-remove-rag: canon block is a pure file composition.

    Asserts each of the four layers is represented in the assembled
    canon_block. We assert on substrings (rather than the full text) so
    the test is robust to formatting changes.
    """

    # Layer 1: outline
    (tmp_path / "outline").mkdir()
    (tmp_path / "outline" / "大纲.md").write_text(
        "主线：寻找玉簪来历。", encoding="utf-8"
    )

    # Layer 2: characters
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "主角.md").write_text(
        "主角害怕旧匣子。", encoding="utf-8"
    )

    # Layer 3: chapter_summaries.json
    manuscript = tmp_path / "manuscript"
    manuscript.mkdir()
    import json

    (manuscript / "chapter_summaries.json").write_text(
        json.dumps(
            {
                "1.1": "主角上山。",
                "1.2": "主角发现旧匣子。",
                "1.3": "匣子里是玉簪。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Layer 4: last chapter
    (manuscript / "chapter-1.2.md").write_text(
        "第一章第二节：主角独自在山中行走。", encoding="utf-8"
    )

    pack = prep_context("1.3", "继续写", project_root=tmp_path, max_tokens=4000)

    assert "大纲.md" in pack.canon_block
    assert "主角" in pack.canon_block
    assert "chapter_summaries" in pack.canon_block
    assert "chapter-1.2.md" in pack.canon_block
    # No [RAG:...] prefix from the deleted embedder path.
    assert "[RAG:" not in pack.canon_block


def test_canon_block_handles_missing_project_root() -> None:
    pack = prep_context("1.1", "继续写", project_root=None, max_tokens=2000)
    assert pack.canon_block
    # Friendlier signal than a stack trace; the S0 path is a real state.
    assert "未绑定项目" in pack.canon_block or "暂无正典资料" in pack.canon_block
