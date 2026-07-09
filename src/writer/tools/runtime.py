"""每次工具调用都会收到的会话级 runtime 配置。

每次工具调用都会收到一个 ``ToolRuntime``，让它能安全地解析路径、
检查能力标志（``shell_enabled``），并尊重内容大小限制。runtime
*不是*全局的 —— 每个会话各自 mint 自己的。
"""

from __future__ import annotations

from pathlib import Path

from writer.tools.errors import ToolDeniedError

# 写入 / 编辑工具的默认路径白名单（per chg-add-write-edit-glob D2）。
# 当路径的祖先（相对于 project_root）属于该集合时即通过。
# ``AGENT.md`` *不在*白名单中 —— 它走 :func:`writer.tools.builtin.file_tools._guard_agent_md`
# 中的专用 3-stage guard。
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
    """工具调用的项目级守卫。

    ``project_root`` 在构造时一次性解析；后续 ``safe_path`` 调用与
    规范化形式对比，阻断基于 symlink 的越界（per 备忘 07 §最小代码）。

    ``allowed_write_paths`` 被 write / edit 工具查阅（per
    ``chg-add-write-edit-glob`` D2 / D7）。为 ``None`` 时 runtime 回退到
    :data:`DEFAULT_WRITE_WHITELIST`；调用方可以覆写以授予额外写根
    （例如 ``"creative_exports"``）或进一步收紧 agent。空 frozenset
    禁用全部写入（fail-closed）。
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
        """把 ``raw`` 解析到 ``project_root`` 下并拒绝越界。

        ``raw`` 可以是相对路径（拼到项目根）或绝对路径；两种情况下，
        解析后的路径都必须位于 ``project_root`` 之内。在检查前通过
        ``Path.resolve()`` 跟随 symlink。
        """

        candidate = (self.project_root / raw).resolve()
        if self.project_root not in (candidate, *candidate.parents):
            raise ToolDeniedError(f"路径越界: {candidate}")
        return candidate

    def require_shell(self) -> None:
        """为会执行 shell 命令的调用点把关。"""
        if not self.shell_enabled:
            raise ToolDeniedError("shell_exec 默认关闭")


__all__ = ["DEFAULT_WRITE_WHITELIST", "ToolRuntime"]
