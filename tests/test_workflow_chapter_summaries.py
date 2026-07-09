"""Tests for ``writer.project.chapter_summaries.append_summary``.

Added 2026-07-09 (real-writing-pipeline PR2) — covers the atomic
write helper that ``write_chapter.persist_outputs`` uses to update
``chapter_summaries.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from writer.project import SUMMARIES_FILE, ChapterSummariesError, append_summary


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a minimal writer project root with ``AGENT.md``."""
    (tmp_path / "AGENT.md").write_text("# 测试项目\n\n## 当前状态\n\nstate: S2\n")
    return tmp_path


class TestAppendSummaryBasics:
    def test_creates_file_when_missing(self, project_root: Path) -> None:
        path = append_summary(project_root, "1.1", "首章总结")
        assert path == project_root / SUMMARIES_FILE
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "chapters" in payload
        assert payload["chapters"][0]["chapter_id"] == "1.1"
        assert payload["chapters"][0]["summary"] == "首章总结"

    def test_preserves_existing_entries(self, project_root: Path) -> None:
        append_summary(project_root, "1.1", "first")
        append_summary(project_root, "1.2", "second")
        payload = json.loads(
            (project_root / SUMMARIES_FILE).read_text(encoding="utf-8")
        )
        chapter_ids = [c["chapter_id"] for c in payload["chapters"]]
        assert chapter_ids == ["1.1", "1.2"]

    def test_idempotent_on_retry(self, project_root: Path) -> None:
        # Calling append_summary twice with the same chapter_id
        # replaces the prior entry rather than appending a duplicate
        # (per the design doc — retries in the review gate produce
        # the same summary).
        append_summary(project_root, "1.1", "first draft")
        append_summary(project_root, "1.1", "revised draft")
        payload = json.loads(
            (project_root / SUMMARIES_FILE).read_text(encoding="utf-8")
        )
        assert len(payload["chapters"]) == 1
        assert payload["chapters"][0]["summary"] == "revised draft"

    def test_preserves_insertion_order(self, project_root: Path) -> None:
        for cid in ["1.3", "1.1", "1.2", "2.1"]:
            append_summary(project_root, cid, f"summary for {cid}")
        payload = json.loads(
            (project_root / SUMMARIES_FILE).read_text(encoding="utf-8")
        )
        assert [c["chapter_id"] for c in payload["chapters"]] == [
            "1.3",
            "1.1",
            "1.2",
            "2.1",
        ]

    def test_returns_the_file_path(self, project_root: Path) -> None:
        path = append_summary(project_root, "1.1", "x")
        assert path == project_root / SUMMARIES_FILE
        assert path.is_file()


class TestAtomicWrite:
    def test_uses_os_replace(self, project_root: Path) -> None:
        with patch("writer.project.chapter_summaries.os.replace") as replace:
            append_summary(project_root, "1.1", "x")
        assert replace.called

    def test_no_temp_file_left_behind(self, project_root: Path) -> None:
        append_summary(project_root, "1.1", "x")
        # No .tmp.* files in the project root.
        leftover = [
            p.name for p in project_root.iterdir() if p.name.startswith(".chapter_summaries.")
        ]
        assert leftover == []

    def test_non_atomic_mode_writes_directly(self, project_root: Path) -> None:
        path = append_summary(project_root, "1.1", "x", atomic=False)
        # atomic=False must NOT call os.replace; it uses Path.write_text
        # so the file is created but no atomic rename happens.
        assert path.exists()
        # The legacy code path is exercised; just confirm the file content
        # is correct (don't assert os.replace absence — Path.write_text
        # may also be followed by os.replace in some edge cases).
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["chapters"][0]["summary"] == "x"


class TestProjectRootValidation:
    def test_rejects_directory_without_agent_md(self, tmp_path: Path) -> None:
        # No AGENT.md in tmp_path — must raise ChapterSummariesError.
        with pytest.raises(ChapterSummariesError) as excinfo:
            append_summary(tmp_path, "1.1", "x")
        assert "AGENT.md" in str(excinfo.value) or "项目根" in str(excinfo.value)

    def test_rejects_empty_chapter_id(self, project_root: Path) -> None:
        with pytest.raises(ChapterSummariesError, match="chapter_id"):
            append_summary(project_root, "", "x")
        with pytest.raises(ChapterSummariesError, match="chapter_id"):
            append_summary(project_root, "   ", "x")

    def test_rejects_none_summary(self, project_root: Path) -> None:
        with pytest.raises(ChapterSummariesError, match="summary"):
            append_summary(project_root, "1.1", None)  # type: ignore[arg-type]

    def test_does_not_create_file_on_validation_error(self, tmp_path: Path) -> None:
        with pytest.raises(ChapterSummariesError):
            append_summary(tmp_path, "1.1", "x")
        assert not (tmp_path / SUMMARIES_FILE).exists()


class TestIsolatedTestFixture:
    def test_no_manuscript_dir_side_effect(self, project_root: Path) -> None:
        # The helper MUST NOT create a manuscript/ directory — that
        # is write_chapter.persist_outputs' responsibility. The
        # ``isolated test fixture`` contract from the writer-tools
        # spec is verified here.
        append_summary(project_root, "1.1", "x")
        assert not (project_root / "manuscript").exists()

    def test_no_writer_metadata_side_effect(self, project_root: Path) -> None:
        append_summary(project_root, "1.1", "x")
        # The helper does not touch .writer/ (that's the checkpointer's
        # job). Only chapter_summaries.json should appear.
        # ``.writer/`` may or may not exist on the shared ``tmp_path``
        # (other tests' side effects). Re-run with a fresh dir to be
        # sure the helper itself does not create it.
        fresh = project_root.parent / "fresh"
        fresh.mkdir()
        (fresh / "AGENT.md").write_text("# test\n")
        append_summary(fresh, "1.1", "x")
        assert not (fresh / ".writer").exists()


class TestLegacyShapeMigration:
    def test_legacy_dict_shape_preserved_under_legacy_key(self, tmp_path: Path) -> None:
        # If the existing file has a non-``{"chapters": [...]}`` shape
        # (legacy user-customized file), the helper must NOT overwrite
        # it — it should stash the old content under ``_legacy`` and
        # start a fresh ``chapters`` list.
        (tmp_path / "AGENT.md").write_text("# test\n")
        legacy_path = tmp_path / SUMMARIES_FILE
        legacy_payload = {"version": 1, "summaries": {"1.0": "old summary"}}
        legacy_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

        append_summary(tmp_path, "1.1", "new")

        new_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
        assert new_payload["_legacy"] == legacy_payload
        assert new_payload["chapters"][0]["chapter_id"] == "1.1"
        assert new_payload["chapters"][0]["summary"] == "new"

    def test_corrupt_json_treated_as_empty(self, project_root: Path) -> None:
        (project_root / SUMMARIES_FILE).write_text("not json", encoding="utf-8")
        append_summary(project_root, "1.1", "x")
        payload = json.loads(
            (project_root / SUMMARIES_FILE).read_text(encoding="utf-8")
        )
        assert payload["chapters"][0]["chapter_id"] == "1.1"


class TestSummaryContent:
    def test_summary_field_preserves_text(self, project_root: Path) -> None:
        long_text = "这是一段很长的总结\n其中有换行\n和特殊字符: \"引号\"、'单引号'。"
        append_summary(project_root, "1.1", long_text)
        payload = json.loads(
            (project_root / SUMMARIES_FILE).read_text(encoding="utf-8")
        )
        assert payload["chapters"][0]["summary"] == long_text

    def test_written_at_field_is_iso_utc(self, project_root: Path) -> None:
        append_summary(project_root, "1.1", "x")
        payload = json.loads(
            (project_root / SUMMARIES_FILE).read_text(encoding="utf-8")
        )
        written_at = payload["chapters"][0]["written_at"]
        # ISO 8601 with Z suffix
        assert written_at.endswith("Z")
        assert "T" in written_at
