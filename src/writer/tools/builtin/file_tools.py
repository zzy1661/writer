"""Path-safe file IO tools.

Both ``SafeReadFile`` and ``SafeListDir`` route their targets through
``ToolRuntime.safe_path`` to reject escapes from ``project_root``.
Outputs are truncated per the runtime's ``max_file_size`` budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


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
            raise NotADirectoryError(f"不是目录: {target}")

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


__all__ = ["SafeListDir", "SafeReadFile"]
