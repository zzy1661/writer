"""Tests for ``writer.workflows.params`` argument parsers.

Added 2026-07-09 (real-writing-pipeline PR2) — covers the
``/创作`` and ``/审核`` argument parsing contract (workflow-owned,
not directive-owned).
"""

from __future__ import annotations

import dataclasses

import pytest

from writer.workflows.params import (
    ReviewChapterArgs,
    WriteChapterArgs,
    extract_review_chapter_args,
    extract_write_chapter_args,
)


class TestExtractWriteChapterArgs:
    def test_no_args_defaults_to_chapter_1_1(self) -> None:
        result = extract_write_chapter_args("/创作")
        assert result == WriteChapterArgs(
            chapter_id="1.1", requirements=(), rewrite=False
        )

    def test_chapter_id_only(self) -> None:
        result = extract_write_chapter_args("/创作 2.3")
        assert result.chapter_id == "2.3"
        assert result.requirements == ()
        assert result.rewrite is False

    def test_chapter_id_and_requirements(self) -> None:
        result = extract_write_chapter_args("/创作 2.4 突出冲突 结尾留钩")
        assert result.chapter_id == "2.4"
        assert result.requirements == ("突出冲突", "结尾留钩")
        assert result.rewrite is False

    def test_rewrite_flag_from_hui_liu(self) -> None:
        result = extract_write_chapter_args("/创作 1.3 请回流重写冲突段落")
        assert result.chapter_id == "1.3"
        assert result.rewrite is True

    def test_rewrite_flag_from_chong_xie(self) -> None:
        result = extract_write_chapter_args("/创作 1.3 重写")
        assert result.rewrite is True

    def test_extra_whitespace_is_stripped(self) -> None:
        result = extract_write_chapter_args("/创作    1.1  ")
        assert result.chapter_id == "1.1"
        assert result.requirements == ()

    def test_strips_command_prefix(self) -> None:
        # The parser handles both ``/创作`` and ``/创作 1.1`` forms;
        # the engine passes the raw user input.
        result_with_prefix = extract_write_chapter_args("/创作 1.5")
        result_without_prefix = extract_write_chapter_args(" 1.5")
        assert result_with_prefix.chapter_id == "1.5"
        # Without the prefix, the first token is the chapter_id.
        assert result_without_prefix.chapter_id == "1.5"

    def test_requirements_preserve_order(self) -> None:
        result = extract_write_chapter_args("/创作 1.1 a b c d")
        assert result.requirements == ("a", "b", "c", "d")

    def test_empty_requirements_when_only_chapter_id(self) -> None:
        result = extract_write_chapter_args("/创作 5.0")
        assert result.requirements == ()

    def test_frozen_dataclass(self) -> None:
        result = extract_write_chapter_args("/创作 1.1")
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            result.chapter_id = "9.9"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


class TestExtractReviewChapterArgs:
    def test_no_args_defaults_to_current(self) -> None:
        result = extract_review_chapter_args("/审核")
        assert result == ReviewChapterArgs(target="current", focus=())

    def test_target_only(self) -> None:
        result = extract_review_chapter_args("/审核 1.3")
        assert result.target == "1.3"
        assert result.focus == ()

    def test_target_and_focus(self) -> None:
        result = extract_review_chapter_args("/审核 1.3 重点看伏笔")
        assert result.target == "1.3"
        assert result.focus == ("重点看伏笔",)

    def test_multiple_focus(self) -> None:
        result = extract_review_chapter_args("/审核 2.4 看节奏 看伏笔 看对话")
        assert result.target == "2.4"
        assert result.focus == ("看节奏", "看伏笔", "看对话")

    def test_no_rewrite_flag_for_review(self) -> None:
        # Review is read-only — even "重写" doesn't trigger anything.
        result = extract_review_chapter_args("/审核 1.1 看看能不能重写")
        assert result.target == "1.1"
        assert result.focus == ("看看能不能重写",)

    def test_extra_whitespace_is_stripped(self) -> None:
        result = extract_review_chapter_args("/审核    1.1   ")
        assert result.target == "1.1"
        assert result.focus == ()


class TestDataclassShapes:
    def test_write_args_is_frozen(self) -> None:
        args = WriteChapterArgs(chapter_id="1.1", requirements=(), rewrite=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            args.chapter_id = "2.2"  # type: ignore[misc]

    def test_review_args_is_frozen(self) -> None:
        args = ReviewChapterArgs(target="1.1", focus=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            args.target = "2.2"  # type: ignore[misc]

    def test_write_args_equality(self) -> None:
        a = WriteChapterArgs(chapter_id="1.1", requirements=("x",), rewrite=False)
        b = WriteChapterArgs(chapter_id="1.1", requirements=("x",), rewrite=False)
        assert a == b

    def test_review_args_equality(self) -> None:
        a = ReviewChapterArgs(target="1.1", focus=("y",))
        b = ReviewChapterArgs(target="1.1", focus=("y",))
        assert a == b
