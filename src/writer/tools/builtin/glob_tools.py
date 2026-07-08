"""Path-safe glob tool.

``SafeGlob`` mirrors Claude Code's ``Glob`` — pattern matching against
``project_root`` using Python :mod:`pathlib` glob semantics. Defaults to
non-recursive (``*``); use the ``**`` prefix for recursive listing.
Hidden entries (``.*``) are skipped, matching ``SafeListDir``'s policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class SafeGlob:
    """Pattern-based file listing under ``project_root``.

    ``pattern`` follows :mod:`pathlib` rules: ``"*.md"`` matches immediate
    children only, ``"**/*.md"`` recurses, ``"manuscript/ch*.md"`` scopes
    to a subdirectory. Hidden entries (``.foo``) are filtered out.
    """

    name = "safe_glob"
    description = (
        "按 glob 模式匹配项目目录内的文件；"
        "支持递归（** 前缀）；按名字或修改时间排序；隐藏文件被忽略。"
    )

    def run(
        self,
        runtime: ToolRuntime,
        *,
        pattern: str,
        sort_by: Literal["name", "mtime"] = "name",
    ) -> ToolResult:
        # Anchor the pattern to project_root and resolve any leading "**"
        # by switching between glob and rglob. We don't pass the pattern
        # through ``safe_path`` because globbing is inherently non-local
        # (a pattern can include ``..`` segments that would be rejected
        # even for legitimate reads) — instead we re-anchor the results.
        if pattern.startswith("**"):
            matches = list(runtime.project_root.glob(pattern))
        else:
            matches = list(runtime.project_root.glob(pattern))

        # Anchor-only patterns ("*", "**") would otherwise include
        # project_root itself; strip the root sentinel entry.
        matches = [m for m in matches if m != runtime.project_root]

        # Drop anything that resolves outside project_root (defense in
        # depth against patterns that somehow escape).
        rel_paths: list[Path] = []
        for m in matches:
            try:
                rel_paths.append(m.relative_to(runtime.project_root))
            except ValueError:
                continue

        # Filter hidden entries (any segment starting with ".").
        rel_paths = [p for p in rel_paths if not any(part.startswith(".") for part in p.parts)]

        if sort_by == "mtime":
            # Sort by the underlying file's mtime, newest first. We resolve
            # back to absolute paths to read mtime — pathlib stores it on
            # the file itself, not on the relative Path.
            rel_paths.sort(
                key=lambda p: -(runtime.project_root / p).stat().st_mtime
            )
        else:  # "name" — the default; deterministic, locale-free sort
            rel_paths.sort(key=lambda p: p.as_posix())

        if not rel_paths:
            return ToolResult(
                output="(无匹配)",
                metadata={"paths": [], "count": 0, "sort_by": sort_by},
            )

        lines = [f"f {p.as_posix()}" for p in rel_paths]
        return ToolResult(
            output="\n".join(lines),
            metadata={
                "paths": [p.as_posix() for p in rel_paths],
                "count": len(rel_paths),
                "sort_by": sort_by,
            },
        )


__all__ = ["SafeGlob"]
