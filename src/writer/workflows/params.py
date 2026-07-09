"""Argument parsing for ``/创作`` and ``/审核`` commands.

These two commands dispatch to workflows (not SKILL.md directives), so
the workflow layer is the natural owner of argument parsing. The
functions in this module are pure — they take a user input string and
return a frozen dataclass; they do NOT touch the engine, the session,
or the filesystem.

Added 2026-07-09 (real-writing-pipeline PR2).

Format:

* ``/创作`` → ``WriteChapterArgs(chapter_id="1.1", requirements=(), rewrite=False)``
* ``/创作 1.3`` → ``WriteChapterArgs(chapter_id="1.3", requirements=(), rewrite=False)``
* ``/创作 2.4 突出冲突 结尾留钩`` → ``WriteChapterArgs(chapter_id="2.4", requirements=("突出冲突", "结尾留钩"), rewrite=False)``
* ``/创作 1.3 请回流重写`` → ``WriteChapterArgs(chapter_id="1.3", requirements=("请回流重写",), rewrite=True)``

* ``/审核`` → ``ReviewChapterArgs(target="current", focus=())``
* ``/审核 1.3`` → ``ReviewChapterArgs(target="1.3", focus=())``
* ``/审核 1.3 重点看伏笔`` → ``ReviewChapterArgs(target="1.3", focus=("重点看伏笔",))``
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WriteChapterArgs:
    """Parsed arguments for the ``/创作`` command.

    Attributes:
        chapter_id: Chapter identifier (defaults to ``"1.1"`` if not
            given). The workflow's ``draft_chapter`` node uses this
            to scope the prep_context canon/history blocks.
        requirements: Tuple of requirement strings ("突出冲突",
            "结尾留钩", etc.). Treated as plain prose — the LLM
            consumes them directly when constructing the prompt.
        rewrite: True when the user input contains a "回流" or
            "重写" trigger. The workflow's review_gate honors this
            flag by routing through the rewrite branch even if the
            LLM verdict would otherwise pass.
    """

    chapter_id: str
    requirements: tuple[str, ...]
    rewrite: bool


@dataclass(frozen=True)
class ReviewChapterArgs:
    """Parsed arguments for the ``/审核`` command.

    Attributes:
        target: Chapter identifier, or the literal string
            ``"current"`` (the default) meaning the latest chapter
            the workflow can locate. The ``load_target_chapter`` node
            in PR3 resolves this to a real path.
        focus: Tuple of focus strings ("重点看伏笔", etc.) passed
            verbatim into the review LLM prompt.
    """

    target: str
    focus: tuple[str, ...]


_REWRITE_TRIGGERS = ("回流", "重写")


def extract_write_chapter_args(user_input: str) -> WriteChapterArgs:
    """Parse a ``/创作`` user input into :class:`WriteChapterArgs`.

    The first token after ``/创作`` (if any) is the ``chapter_id``;
    remaining tokens become ``requirements`` (in order). If the user
    input contains ``"回流"`` or ``"重写"``, ``rewrite`` is set to
    True regardless of where the trigger word appears.
    """
    stripped = user_input.removeprefix("/创作").strip()
    if not stripped:
        return WriteChapterArgs(chapter_id="1.1", requirements=(), rewrite=False)

    tokens = stripped.split()
    chapter_id = tokens[0] if tokens else "1.1"
    requirements = tuple(tokens[1:])
    rewrite = any(trigger in stripped for trigger in _REWRITE_TRIGGERS)
    return WriteChapterArgs(
        chapter_id=chapter_id,
        requirements=requirements,
        rewrite=rewrite,
    )


def extract_review_chapter_args(user_input: str) -> ReviewChapterArgs:
    """Parse a ``/审核`` user input into :class:`ReviewChapterArgs`.

    The first token after ``/审核`` (if any) is the ``target``;
    remaining tokens become ``focus``. No triggers are recognised
    (review is a read-only flow).
    """
    stripped = user_input.removeprefix("/审核").strip()
    if not stripped:
        return ReviewChapterArgs(target="current", focus=())

    tokens = stripped.split()
    target = tokens[0] if tokens else "current"
    focus = tuple(tokens[1:])
    return ReviewChapterArgs(target=target, focus=focus)


__all__ = [
    "ReviewChapterArgs",
    "WriteChapterArgs",
    "extract_review_chapter_args",
    "extract_write_chapter_args",
]
