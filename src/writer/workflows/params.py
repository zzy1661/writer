"""``/创作`` / ``/审核`` / ``/骨架`` 命令的参数解析。

这三个命令派发到工作流（而非 SKILL.md directives），所以工作流层
是参数解析的自然所有者。本模块的函数是纯函数 —— 接受用户输入
字符串并返回冻结 dataclass；它们*不*触碰引擎、会话或文件系统。

2026-07-09 增补（real-writing-pipeline PR2）；2026-07-17 增补 ``/骨架``。

格式：

* ``/创作`` → ``WriteChapterArgs(chapter_id="1.1", requirements=(), rewrite=False)``
* ``/创作 1.3`` → ``WriteChapterArgs(chapter_id="1.3", requirements=(), rewrite=False)``
* ``/创作 2.4 突出冲突 结尾留钩`` → ``WriteChapterArgs(chapter_id="2.4", requirements=("突出冲突", "结尾留钩"), rewrite=False)``
* ``/创作 1.3 请回流重写`` → ``WriteChapterArgs(chapter_id="1.3", requirements=("请回流重写",), rewrite=True)``

* ``/审核`` → ``ReviewChapterArgs(target="current", focus=())``
* ``/审核 1.3`` → ``ReviewChapterArgs(target="1.3", focus=())``
* ``/审核 1.3 重点看伏笔`` → ``ReviewChapterArgs(target="1.3", focus=("重点看伏笔",))``

* ``/骨架`` → ``SkeletonArgs(mode="full", ...)``
* ``/骨架 卷一`` → ``SkeletonArgs(mode="volume", volume="卷一", ...)``
* ``/骨架 1.1-1.20`` → ``SkeletonArgs(mode="range", start="1.1", end="1.20", ...)``

``/骨架`` 的 ``rewrite`` / ``continue_`` / ``view`` 字段在 PR1 仅占位解析
不实装语义，分别在 PR1.5 / PR2 落地（per ``TODO/骨架命令.md`` §12）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from writer.skills.errors import SkillError


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

# 卷名正则：卷一..卷九九（per `_TOC_PATHS` 中 `大纲/章节目录.md` 用法）
_VOLUME_PATTERN = re.compile(r"^卷([一二三四五六七八九十])$")

# 章节区间正则：双层 1.1-1.20 / 跨卷 1.1-2.20
_RANGE_PATTERN = re.compile(r"^(\d+\.\d+)-(\d+\.\d+)$")


@dataclass(frozen=True)
class SkeletonArgs:
    """``/骨架`` 命令解析后的参数。

    Attributes:
        mode: 解析后的执行模式。``"full"`` 全书（按 TOC 全量）；
            ``"volume"`` 仅指定卷；``"range"`` 按章节 ID 区间。
        volume: ``mode="volume"`` 时指定卷名（例 ``"卷一"``），其余为空。
        start: ``mode="range"`` 时区间起点章节 ID（例 ``"1.1"``）。
        end: ``mode="range"`` 时区间终点章节 ID（例 ``"1.20"``）。
        rewrite: 用户触发词（``"重写"`` / ``"覆盖"``）。PR1 **仅占位**，
            实装语义推 PR2。
        continue_: 续跑标志。PR1 **仅占位**，实装语义推 PR2。
        view: 只读预览标志。PR1 **仅占位**，实装语义推 PR1.5。

    2026-07-17 增补（chg-skeleton-chapters-pr1）。
    """

    mode: Literal["full", "volume", "range"]
    volume: str = ""
    start: str = ""
    end: str = ""
    rewrite: bool = False
    continue_: bool = False
    view: bool = False


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


def extract_skeleton_args(user_input: str) -> SkeletonArgs:
    """把 ``/骨架`` 用户输入解析为 :class:`SkeletonArgs`。

    解析规则：

    * 空（仅 ``/骨架``） → ``SkeletonArgs(mode="full")``
    * 第一 token 匹配 ``^卷[一-十]$`` → ``SkeletonArgs(mode="volume", volume=<token>)``
    * 第一 token 匹配 ``^\\d+\\.\\d+-\\d+\\.\\d+$`` → ``SkeletonArgs(mode="range", start=<left>, end=<right>)``
    * 其他形式 → :class:`SkillError`

    PR1 范围内 ``rewrite`` / ``continue_`` / ``view`` 字段为占位
    (恒 ``False``)。PR1.5 / PR2 实装后，这些字段会在输入中
    匹配 ``"rewrite"`` / ``"覆盖"`` / ``"continue"`` / ``"续"`` /
    ``"view"`` / ``"预览"`` 等触发词（per ``TODO/骨架命令.md`` §9）。
    """
    stripped = user_input.removeprefix("/骨架").strip()
    if not stripped:
        return SkeletonArgs(mode="full")

    first_token = stripped.split(maxsplit=1)[0]

    # 卷名形式
    volume_match = _VOLUME_PATTERN.match(first_token)
    if volume_match is not None:
        return SkeletonArgs(mode="volume", volume=first_token)

    # 区间形式（双层 1.1-1.20 / 跨卷 1.1-2.20）
    range_match = _RANGE_PATTERN.match(first_token)
    if range_match is not None:
        start, end = range_match.groups()
        return SkeletonArgs(mode="range", start=start, end=end)

    # 未知形式 → 拒。单层 `1-20` 不接受（与 chapter_id="1.1" 双层约定对齐）
    raise SkillError(
        f"无效章节范围: 应为 X.Y-X.Z 形式（如 1.1-1.20），收到 {first_token!r}"
    )


__all__ = [
    "ReviewChapterArgs",
    "SkeletonArgs",
    "WriteChapterArgs",
    "extract_review_chapter_args",
    "extract_skeleton_args",
    "extract_write_chapter_args",
]
