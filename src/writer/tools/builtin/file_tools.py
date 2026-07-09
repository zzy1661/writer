"""Path-safe file IO tools.

``SafeReadFile``, ``SafeListDir``, ``SafeWriteFile`` and ``SafeEditFile``
route their targets through ``ToolRuntime.safe_path`` to reject escapes
from ``project_root``. Reads truncate to ``max_file_size``; writes refuse
to escape the runtime's ``allowed_write_paths`` whitelist and apply a
3-stage guard on ``AGENT.md`` (see ``_guard_agent_md``).
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


# Genre regex duplicated from writer.project.read_genre_from_agent so the
# guard can both *extract* and *insert* without a circular import back into
# writer.project (tools layer should not import writer.project.* broadly;
# state.py is the allowed exception for this shared constant).
_GENRE_LINE_RE = re.compile(r"^- 题材:\s*(.+?)\s*$", re.MULTILINE)


class SafeReadFile:
    """Read a UTF-8 text file inside ``project_root``.

    Over-long content is truncated to the runtime's ``max_file_size``
    and flagged via ``ToolResult.truncated`` so callers can re-query
    with a narrower window.
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
    """List directory entries under ``project_root``.

    Returns one entry per line prefixed by a ``d``/``f`` marker. Hidden
    files (``.*``) are skipped to keep the result LLM-friendly.
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
# SafeWriteFile + helpers (per chg-add-write-edit-glob D1-D4)
# ---------------------------------------------------------------------------


def _check_whitelist(target: Path, runtime: ToolRuntime) -> None:
    """Reject paths whose first segment is not in the write whitelist.

    ``Path.parts[0]`` is the topmost segment relative to ``project_root``;
    AGENT.md at the project root has parts = ``()`` after stripping the root,
    so it falls into the empty-string bucket and is rejected here *before*
    the AGENT.md guard runs — the guard then re-allows it via the
    :func:`_guard_agent_md` exemption path. See :meth:`SafeWriteFile.run`.
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
    """Write ``content`` to ``target`` atomically via tmp + ``os.replace``.

    The tmp suffix uses a short uuid slice to keep the visible filesystem
    tidy in the rare crash path (operator can still inspect ``.tmp.*``
    files manually if a power-loss leaves them behind).
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
    """Copy an existing file to ``.writer/backups/<relpath>.<ISO-ts>``.

    Returns the backup path, or ``None`` if there was nothing to back up.
    Creates the backups root on first use.
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
    """Return the ``- 题材: <genre>`` text (without leading dash) or ``None``."""

    m = _GENRE_LINE_RE.search(content)
    return m.group(1).strip() if m else None


def _insert_genre_line(content: str, genre: str) -> str:
    """Insert ``- 题材: <genre>`` into the ``## 当前状态`` block.

    Appends the line right after the section header so the file remains
    parseable by :func:`writer.project.read_genre_from_agent`. If the
    section header is missing this is a no-op (the AGENT.md guard will
    already have rejected the write, but we keep this defensive).
    """

    needle = f"{CURRENT_STATE_SECTION_HEADER}\n"
    if needle not in content:
        return content
    return content.replace(needle, f"{needle}- 题材: {genre}\n", 1)


def _guard_agent_md(
    target: Path, content: str, mode: str
) -> tuple[str, dict[str, object]]:
    """Apply the 3-stage AGENT.md guard; return ``(maybe_patched, meta)``.

    Guard 1: ``mode`` MUST be ``overwrite``.
    Guard 2: ``content`` MUST contain the ``## 当前状态`` section.
    Guard 3: if existing file has ``题材: <g>`` and new content lacks it,
    the genre line is merged in.

    Returns the (possibly patched) content plus metadata dict for
    ``ToolResult.metadata``.
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
    """Write UTF-8 text files inside ``project_root``.

    ``mode`` controls intent:
    - ``create`` (default): refuse if file exists.
    - ``overwrite``: atomic replace; pre-write backup unless ``backup=False``.
    - ``append``: tail-add; non-atomic, no backup.

    All writes pass through the runtime's path whitelist
    (see :data:`writer.tools.runtime.DEFAULT_WRITE_WHITELIST`). Writes to
    ``AGENT.md`` additionally pass the 3-stage guard in :func:`_guard_agent_md`.
    Content larger than ``runtime.max_file_size`` is rejected.
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
        # AGENT.md bypasses the whitelist (its first segment is empty);
        # all other paths go through the normal whitelist check.
        if target.name != "AGENT.md":
            _check_whitelist(target, runtime)

        # Size gate applies to the *new* content, regardless of mode.
        if len(content.encode("utf-8")) > runtime.max_file_size:
            raise ToolOutputTooLargeError(
                f"写入内容 {len(content)} 字节超出 max_file_size={runtime.max_file_size}"
            )

        # AGENT.md guard runs AFTER size check so a too-large AGENT.md
        # write fails fast with the clearer "too large" error.
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
        else:  # pragma: no cover — Literal exhaustiveness guard
            raise ToolDeniedError(f"未知 mode: {mode}")

        metadata["bytes_written"] = len(content.encode("utf-8"))
        metadata["mtime"] = datetime.now(UTC).isoformat()
        metadata.update(agent_meta)

        return ToolResult(
            output=f"已写入 {target} ({metadata['bytes_written']} 字节, mode={mode})",
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# SafeEditFile + helpers (per chg-add-write-edit-glob D5)
# ---------------------------------------------------------------------------


def _apply_edit(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> tuple[str, int]:
    """Apply the Edit; return ``(new_content, replace_count)``.

    Uniqueness is enforced by the caller via ``replace_all`` — this helper
    trusts the flag and just does the substitution. Splitting the policy
    (count + decide) from the mechanism (substitute) keeps the test
    surface clean.
    """

    count = content.count(old_string)
    if replace_all:
        return content.replace(old_string, new_string), count
    return content.replace(old_string, new_string, 1), 1


def _unified_diff(old_content: str, new_content: str, path: str) -> str:
    """Tiny unified diff built from :func:`difflib.unified_diff``.

    Returns the empty string if both contents are identical. We avoid the
    full difflib machinery in the import-time path by doing the work in
    a private helper — the tool imports :mod:`difflib` lazily here.
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
    """Exact string replace — Claude Code Edit semantics.

    The tool requires ``old_string`` to be unique unless ``replace_all=True``.
    On a hit, the new content is written atomically with an optional backup.
    ``dry_run=True`` returns the would-be diff in metadata without touching
    disk; combined with the AGENT.md guard this makes LLM-driven edits
    reviewable before commit.
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

        # AGENT.md guard: pass through the same 3-stage check that
        # SafeWriteFile uses. The new content is what the file will be
        # AFTER the edit; the existing file already has the genre line
        # (the edit wouldn't reach this point otherwise for AGENT.md).
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
