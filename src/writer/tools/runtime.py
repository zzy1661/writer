"""Per-session runtime knobs handed to every tool invocation.

Each tool call receives a ``ToolRuntime`` so it can resolve paths safely,
check capability flags (``shell_enabled``), and respect content-size
limits. The runtime is *not* a global — each session mints its own.
"""

from __future__ import annotations

from pathlib import Path

from writer.tools.errors import ToolDeniedError

# Default path whitelist for write/edit tools (per chg-add-write-edit-glob D2).
# A path passes when its first segment (relative to project_root) is in this
# set. ``AGENT.md`` is NOT in the whitelist — it goes through the dedicated
# 3-stage guard in :func:`writer.tools.builtin.file_tools._guard_agent_md`.
DEFAULT_WRITE_WHITELIST: frozenset[str] = frozenset(
    {
        "manuscript",
        "outline",
        "characters",
        "world",
        "notes",
        "创意",
        ".writer/cache",
        ".writer/agents",
    }
)


class ToolRuntime:
    """Project-scoped guards for tool invocations.

    ``project_root`` is resolved once at construction; subsequent
    ``safe_path`` calls compare against the canonical form, which blocks
    symlink-based escapes (per 备忘 07 §最小代码).

    ``allowed_write_paths`` is consulted by write/edit tools (per
    ``chg-add-write-edit-glob`` D2 / D7). When ``None`` the runtime falls
    back to :data:`DEFAULT_WRITE_WHITELIST`; callers can override it to
    grant additional write roots (e.g. ``"creative_exports"``) or restrict
    the agent further. An empty frozenset disables all writes
    (fail-closed).
    """

    def __init__(
        self,
        project_root: Path,
        *,
        shell_enabled: bool = False,
        max_file_size: int = 50_000,
        allowed_write_paths: frozenset[str] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.shell_enabled = shell_enabled
        self.max_file_size = max_file_size
        self.allowed_write_paths = (
            allowed_write_paths
            if allowed_write_paths is not None
            else DEFAULT_WRITE_WHITELIST
        )

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


__all__ = ["DEFAULT_WRITE_WHITELIST", "ToolRuntime"]
