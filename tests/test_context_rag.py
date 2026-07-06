from __future__ import annotations

from pathlib import Path

from writer.context import prep_context, trim_to_budget
from writer.rag import ProjectRagIndex, collect_project_documents


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


def test_project_rag_indexes_outline_characters_and_manuscript(tmp_path: Path) -> None:
    (tmp_path / "outline").mkdir()
    (tmp_path / "characters").mkdir()
    (tmp_path / "manuscript").mkdir()
    (tmp_path / "outline" / "大纲.md").write_text("主线：寻找玉簪来历。", encoding="utf-8")
    (tmp_path / "characters" / "主角.md").write_text("主角害怕旧匣子。", encoding="utf-8")
    (tmp_path / "manuscript" / "chapter-01.md").write_text(
        "第一章埋下伏笔：F003 玉簪藏在旧匣子夹层。",
        encoding="utf-8",
    )

    docs = collect_project_documents(tmp_path)
    hits = ProjectRagIndex(tmp_path).query("第 N 章回收玉簪伏笔", k=3)

    assert len(docs) == 3
    assert any("F003" in hit.text for hit in hits)
    assert any(hit.source == "manuscript/chapter-01.md" for hit in hits)
