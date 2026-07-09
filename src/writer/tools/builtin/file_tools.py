"""路径安全的文件 IO 工具。

``SafeReadFile``、``SafeListDir``、``SafeWriteFile`` 和 ``SafeEditFile``
把所有目标路径走 ``ToolRuntime.safe_path``，以拒绝逃出 ``project_root``
的越界。读取按 ``max_file_size`` 截断；写入拒绝逃出 runtime
``allowed_write_paths`` 白名单，并对 ``AGENT.md`` 应用 3-stage guard
（见 ``_guard_agent_md``）。
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from writer.project.state import CURRENT_STATE_SECTION_HEADER
from writer.tools.errors import (
    ToolDeniedError,
    ToolNotADirectoryError,
    ToolOutputTooLargeError,
)
from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


# 题材正则从 writer.project.read_genre_from_agent 复制，让 guard 既能
# *抽取*又能*插入*，无需回到 writer.project 形成循环（tools 层不应
# 广泛 import writer.project.*；state.py 是这个共享常量的允许例外）。
_GENRE_LINE_RE = re.compile(r"^- 题材:\s*(.+?)\s*$", re.MULTILINE)


class SafeReadFile:
    """读取 ``project_root`` 内的 UTF-8 文本文件。

    超长内容按 runtime 的 ``max_file_size`` 截断，并通过
    ``ToolResult.truncated`` 标记，方便调用方用更窄的窗口重新查询。
    """

    name = "safe_read_file"
    description = "读取项目目录内的 UTF-8 文本文件;路径越界会被拒绝,超长内容自动截断。"

    def run(self, runtime: ToolRuntime, *, path: str) -> ToolResult:
        target = runtime.safe_path(path)
        content = target.read_text(encoding="utf-8")
        budget = runtime.max_file_size
        if len(content) > budget:
            truncated = content[:budget]
            return ToolResult(
                output=truncated + "\n\n[内容已截断,请分段读取]",
                truncated=True,
                metadata={"path": str(target), "original_size": len(content)},
            )
        return ToolResult(
            output=content,
            metadata={"path": str(target), "size": len(content)},
        )


class SafeListDir:
    """列出 ``project_root`` 下的目录条目。

    每行一条，前缀 ``d``/``f`` 标记。隐藏文件（``.*``）会被跳过，
    让结果对 LLM 友好。
    """

    name = "safe_list_dir"
    description = "列出项目目录内的文件和子目录;路径越界会被拒绝;隐藏文件被忽略。"

    def run(self, runtime: ToolRuntime, *, path: str = ".") -> ToolResult:
        target = runtime.safe_path(path)
        if not target.is_dir():
            raise ToolNotADirectoryError(f"不是目录: {target}")

        lines: list[str] = []
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            marker = "d" if entry.is_dir() else "f"
            lines.append(f"{marker} {entry.name}")

        return ToolResult(
            output="\n".join(lines) if lines else "(空目录)",
            metadata={"path": str(target), "count": len(lines)},
        )


# ---------------------------------------------------------------------------
# SafeWriteFile + helpers（per chg-add-write-edit-glob D1-D4）
# ---------------------------------------------------------------------------


def _check_whitelist(target: Path, runtime: ToolRuntime) -> None:
    """拒绝首段不在写入白名单中的路径。

    ``Path.parts[0]`` 是相对于 ``project_root`` 的最顶层段；
    项目根处的 AGENT.md 去掉根后 parts 为 ``()``，因此落入空串桶，
    在此被拒绝 —— 这发生在 AGENT.md guard 之前，guard 后续通过
    :func:`_guard_agent_md` 的豁免路径再允许它。见 :meth:`SafeWriteFile.run`。
    """

    try:
        rel = target.relative_to(runtime.project_root)
    except ValueError as err:
        raise ToolDeniedError(f"路径越界: {target}") from err
    first = rel.parts[0] if rel.parts else ""
    if first not in runtime.allowed_write_paths:
        raise ToolDeniedError(
            f"写入路径 {target.name!r} 不在白名单 {sorted(runtime.allowed_write_paths)} 内"
        )


def _atomic_write(target: Path, content: str) -> None:
    """通过 tmp + ``os.replace`` 原子地把 ``content`` 写入 ``target``。

    tmp 后缀使用短 uuid 切片，让罕见的崩溃路径下文件系统保持整洁
    （如果断电留下 tmp 文件，运维仍可手动检查 ``.tmp.*`` 文件）。
    """

    tmp = target.with_name(target.name + f".tmp.{uuid4().hex[:8]}")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _backup_original(target: Path, runtime: ToolRuntime) -> Path | None:
    """把已有文件复制到 ``.writer/backups/<relpath>.<ISO-ts>``。

    返回备份路径，若无可备份内容则返回 ``None``。首次使用时创建
    backups 根。
    """

    if not target.exists():
        return None
    try:
        rel = target.relative_to(runtime.project_root)
    except ValueError:
        return None
    backups_root = runtime.project_root / ".writer" / "backups" / rel.parent
    backups_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    backup = backups_root / f"{target.name}.{ts}"
    shutil.copy2(target, backup)
    return backup


def _extract_genre_line(content: str) -> str | None:
    """返回 ``- 题材: <genre>`` 文本（不带前导 dash），或 ``None``。"""

    m = _GENRE_LINE_RE.search(content)
    return m.group(1).strip() if m else None


def _insert_genre_line(content: str, genre: str) -> str:
    """把 ``- 题材: <genre>`` 插入 ``## 当前状态`` 段。

    把该行追加在段头之后，让文件仍可被
    :func:`writer.project.read_genre_from_agent` 解析。若段头缺失，
    本函数为 no-op（AGENT.md guard 已拒绝该写入，但此处保持防御性）。
    """

    needle = f"{CURRENT_STATE_SECTION_HEADER}\n"
    if needle not in content:
        return content
    return content.replace(needle, f"{needle}- 题材: {genre}\n", 1)


def _guard_agent_md(
    target: Path, content: str, mode: str
) -> tuple[str, dict[str, object]]:
    """应用 3-stage AGENT.md guard；返回 ``(可能的修补后内容, meta)``。

    Guard 1：``mode`` 必须为 ``overwrite``。
    Guard 2：``content`` 必须包含 ``## 当前状态`` 段。
    Guard 3：若现有文件含 ``题材: <g>`` 且新内容缺失该行，
    则把题材行合并进来。

    返回（可能经过修补的）内容和供 ``ToolResult.metadata`` 使用的
    元数据字典。
    """

    if target.name != "AGENT.md":
        return content, {}

    if mode != "overwrite":
        raise ToolDeniedError(
            "AGENT.md 仅允许 mode=overwrite；create/append 会破坏元信息结构"
        )

    if CURRENT_STATE_SECTION_HEADER not in content:
        raise ToolDeniedError(
            f"AGENT.md 必须包含 {CURRENT_STATE_SECTION_HEADER!r} 段；"
            "如需新增状态字段请保留该段"
        )

    meta: dict[str, object] = {}
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        preserved_genre = _extract_genre_line(existing)
        if preserved_genre and preserved_genre not in content:
            content = _insert_genre_line(content, preserved_genre)
            meta["preserved_genre"] = preserved_genre
            meta["genre_guard_triggered"] = True
    return content, meta


def _sha256_first8(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


class SafeWriteFile:
    """在 ``project_root`` 内写入 UTF-8 文本文件。

    ``mode`` 控制意图：
    - ``create``（默认）：文件已存在则拒绝。
    - ``overwrite``：原子替换；除 ``backup=False`` 外做写前备份。
    - ``append``：尾部追加；非原子、无备份。

    所有写入都经过 runtime 的路径白名单
    （见 :data:`writer.tools.runtime.DEFAULT_WRITE_WHITELIST`）。
    对 ``AGENT.md`` 的写入还要过 :func:`_guard_agent_md` 的 3-stage guard。
    超过 ``runtime.max_file_size`` 的内容会被拒绝。
    """

    name = "safe_write_file"
    description = (
        "在项目目录白名单内创建/覆盖/追加 UTF-8 文本文件；"
        "路径越界与超长内容会被拒绝；AGENT.md 仅允许 overwrite 并自动保留题材行。"
    )

    def run(
        self,
        runtime: ToolRuntime,
        *,
        path: str,
        content: str,
        mode: Literal["create", "overwrite", "append"] = "create",
        backup: bool = True,
    ) -> ToolResult:
        target = runtime.safe_path(path)
        # AGENT.md 绕过白名单（其首段为空）；其余路径走常规白名单检查。
        if target.name != "AGENT.md":
            _check_whitelist(target, runtime)

        # 大小门槛作用于 *新* 内容，与 mode 无关。
        if len(content.encode("utf-8")) > runtime.max_file_size:
            raise ToolOutputTooLargeError(
                f"写入内容 {len(content)} 字节超出 max_file_size={runtime.max_file_size}"
            )

        # AGENT.md guard 在 size 检查之后运行，让过大的 AGENT.md
        # 写入以更明确的"过大"错误快速失败。
        content, agent_meta = _guard_agent_md(target, content, mode)

        metadata: dict[str, object] = {
            "mode": mode,
            "sha256_first8": _sha256_first8(content),
        }

        if mode == "create":
            if target.exists():
                raise ToolDeniedError(
                    f"文件已存在: {target}；若要覆盖请显式 mode=overwrite"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, content)
        elif mode == "overwrite":
            backup_path = _backup_original(target, runtime) if backup else None
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, content)
            if backup_path is not None:
                metadata["backup_path"] = str(backup_path)
        elif mode == "append":
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content)
        else:  # pragma: no cover — Literal 完备性 guard
            raise ToolDeniedError(f"未知 mode: {mode}")

        metadata["bytes_written"] = len(content.encode("utf-8"))
        metadata["mtime"] = datetime.now(UTC).isoformat()
        metadata.update(agent_meta)

        return ToolResult(
            output=f"已写入 {target} ({metadata['bytes_written']} 字节, mode={mode})",
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# SafeEditFile + helpers（per chg-add-write-edit-glob D5）
# ---------------------------------------------------------------------------


def _apply_edit(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> tuple[str, int]:
    """应用编辑；返回 ``(new_content, replace_count)``。

    唯一性由调用方通过 ``replace_all`` 强制 —— 本 helper 信任该标志
    只做替换。把策略（计数 + 决策）与机制（替换）分开，让测试表面
    保持清爽。
    """

    count = content.count(old_string)
    if replace_all:
        return content.replace(old_string, new_string), count
    return content.replace(old_string, new_string, 1), 1


def _unified_diff(old_content: str, new_content: str, path: str) -> str:
    """基于 :func:`difflib.unified_diff` 的小巧 unified diff。

    两个内容相同时返回空串。我们通过私有 helper 完成工作，避免在
    import 时引入完整 difflib —— 工具在此延迟 import :mod:`difflib`。
    """

    if old_content == new_content:
        return ""
    import difflib

    diff = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


class SafeEditFile:
    """精确字符串替换 —— Claude Code Edit 语义。

    除非 ``replace_all=True``，否则要求 ``old_string`` 唯一。命中时，
    新内容以可选备份原子写入。``dry_run=True`` 通过 metadata 返回
    拟定的 diff 而不触盘；与 AGENT.md guard 一起，让 LLM 驱动的编辑
    在提交前可审阅。
    """

    name = "safe_edit_file"
    description = (
        "对项目目录白名单内的文件做精确字符串替换；"
        "old_string 不唯一且未传 replace_all 会拒绝；"
        "支持 dry_run 仅返回 diff 不写盘；"
        "AGENT.md 仅允许 overwrite 并自动保留题材行。"
    )

    def run(
        self,
        runtime: ToolRuntime,
        *,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        dry_run: bool = False,
        backup: bool = True,
    ) -> ToolResult:
        if old_string == new_string:
            raise ToolDeniedError("old_string == new_string，无修改")

        target = runtime.safe_path(path)
        if not target.exists():
            raise ToolDeniedError(f"文件不存在: {target}")
        if target.name != "AGENT.md":
            _check_whitelist(target, runtime)

        old_content = target.read_text(encoding="utf-8")
        count = old_content.count(old_string)
        if count == 0:
            raise ToolDeniedError(f"未找到 old_string: {old_string!r}")
        if count > 1 and not replace_all:
            raise ToolDeniedError(
                f"old_string 出现 {count} 次；若要全部替换请显式 replace_all=True"
            )

        new_content, applied = _apply_edit(
            old_content, old_string, new_string, replace_all
        )

        if len(new_content.encode("utf-8")) > runtime.max_file_size:
            raise ToolOutputTooLargeError(
                f"编辑后内容 {len(new_content)} 字节超出 max_file_size={runtime.max_file_size}"
            )

        diff_text = _unified_diff(old_content, new_content, str(target))

        metadata: dict[str, object] = {
            "replace_count": applied,
            "dry_run": dry_run,
            "diff": diff_text,
        }
        if len(old_string) > 0 and len(old_string) * 2 > len(old_content):
            metadata["large_edit_warning"] = True

        if dry_run:
            return ToolResult(
                output=f"[dry_run] 拟替换 {applied} 处；diff {len(diff_text)} 字节",
                metadata=metadata,
            )

        # AGENT.md guard：与 SafeWriteFile 走相同的 3-stage 检查。
        # 新内容是编辑*之后*的内容；AGENT.md 的编辑能走到这里
        # 说明现有文件已有题材行。
        if target.name == "AGENT.md":
            new_content, agent_meta = _guard_agent_md(target, new_content, "overwrite")
            metadata.update(agent_meta)

        backup_path = _backup_original(target, runtime) if backup else None
        _atomic_write(target, new_content)
        if backup_path is not None:
            metadata["backup_path"] = str(backup_path)

        return ToolResult(
            output=f"已替换 {applied} 处：{target}",
            metadata=metadata,
        )


__all__ = ["SafeEditFile", "SafeListDir", "SafeReadFile", "SafeWriteFile"]
