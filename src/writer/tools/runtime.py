"""Per-session runtime knobs handed to every tool invocation.

Each tool call receives a ``ToolRuntime`` so it can resolve paths safely,
check capability flags (``shell_enabled``), and respect content-size
limits. The runtime is *not* a global — each session mints its own.
"""

from __future__ import annotations

from pathlib import Path

from writer.tools.errors import ToolDeniedError


class ToolRuntime:
    """Project-scoped guards for tool invocations.

    ``project_root`` is resolved once at construction; subsequent
    ``safe_path`` calls compare against the canonical form, which blocks
    symlink-based escapes (per 备忘 07 §最小代码).
    """

    def __init__(
        self,
        project_root: Path,
        *,
        shell_enabled: bool = False,
        max_file_size: int = 50_000,
    ) -> None:
        self.project_root = project_root.resolve()
        self.shell_enabled = shell_enabled
        self.max_file_size = max_file_size

    def safe_path(self, raw: str | Path) -> Path:
        """Resolve ``raw`` against ``project_root`` and reject escapes.

        ``raw`` may be relative (joined to project root) or absolute; in
        both cases the resulting path must live inside ``project_root``.
        Symlinks are followed via ``Path.resolve()`` before the check.
        """

        candidate = (self.project_root / raw).resolve()
        if self.project_root not in (candidate, *candidate.parents):
            raise ToolDeniedError(f"路径越界: {candidate}")
        return candidate

    def require_shell(self) -> None:
        """Guard call sites that would execute shell commands."""
        if not self.shell_enabled:
            raise ToolDeniedError("shell_exec 默认关闭")


__all__ = ["ToolRuntime"]
