"""``/创作`` 和 ``/审核`` 命令的参数解析。

这两个命令派发到工作流（而非 SKILL.md directives），所以工作流层
是参数解析的自然所有者。本模块的函数是纯函数 —— 接受用户输入
字符串并返回冻结 dataclass；它们*不*触碰引擎、会话或文件系统。

2026-07-09 增补（real-writing-pipeline PR2）。

格式：

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
    """``/创作`` 命令解析后的参数。

    Attributes:
        chapter_id: 章节标识符（未给出时默认为 ``"1.1"``）。
            工作流的 ``draft_chapter`` 节点用它限定
            prep_context canon/history 块。
        requirements: 需求字符串的 tuple（"突出冲突"、"结尾留钩" 等）。
            视为纯散文 —— LLM 在构造 prompt 时直接消费。
        rewrite: 用户输入包含 "回流" 或 "重写" 触发词时为 True。
            工作流的 review_gate 通过走 rewrite 分支来尊重该标志，
            即使 LLM 判定本应通过。
    """

    chapter_id: str
    requirements: tuple[str, ...]
    rewrite: bool


@dataclass(frozen=True)
class ReviewChapterArgs:
    """``/审核`` 命令解析后的参数。

    Attributes:
        target: 章节标识符，或字面字符串 ``"current"``（默认），
            含义是工作流能定位到的最新章节。PR3 的
            ``load_target_chapter`` 节点把它解析为真实路径。
        focus: 关注点字符串的 tuple（"重点看伏笔" 等），原样传入
            review LLM prompt。
    """

    target: str
    focus: tuple[str, ...]


_REWRITE_TRIGGERS = ("回流", "重写")


def extract_write_chapter_args(user_input: str) -> WriteChapterArgs:
    """把 ``/创作`` 用户输入解析为 :class:`WriteChapterArgs`。

    ``/创作`` 后第一个 token（如果有）是 ``chapter_id``；剩余 token
    成为 ``requirements``（按顺序）。如果用户输入包含 ``"回流"`` 或
    ``"重写"``，``rewrite`` 被设为 True，无论触发词出现在哪里。
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
    """把 ``/审核`` 用户输入解析为 :class:`ReviewChapterArgs`。

    ``/审核`` 后第一个 token（如果有）是 ``target``；剩余 token 成为
    ``focus``。不识别任何触发词（review 是只读流程）。
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
