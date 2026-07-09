"""路径安全的 glob 工具。

``SafeGlob`` 与 Claude Code 的 ``Glob`` 对齐 —— 用 Python :mod:`pathlib`
glob 语义在 ``project_root`` 下做模式匹配。默认非递归（``*``）；用
``**`` 前缀做递归列出。隐藏条目（``.*``）被跳过，与 ``SafeListDir``
策略一致。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class SafeGlob:
    """``project_root`` 下的基于模式的文件列出。

    ``pattern`` 遵循 :mod:`pathlib` 规则：``"*.md"`` 只匹配直接子项；
    ``"**/*.md"`` 递归；``"manuscript/ch*.md"`` 限定子目录。隐藏条目
    （``.foo``）会被过滤。
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
        # 把模式锚定到 project_root，把前导 "**" 通过在 glob 与
        # rglob 之间切换来解析。我们不把模式过 ``safe_path``，因为
        # glob 本质上是非局部的（模式可能包含 ``..`` 段，即便合法的
        # 读取也会被拒）—— 改为对结果重新锚定。
        if pattern.startswith("**"):
            matches = list(runtime.project_root.glob(pattern))
        else:
            matches = list(runtime.project_root.glob(pattern))

        # 仅锚定模式（"*", "****）会包含 project_root 本身；
        # 剔除根哨兵条目。
        matches = [m for m in matches if m != runtime.project_root]

        # 丢弃解析到 project_root 之外的内容（纵深防御，挡住任何
        # 设法逃逸的模式）。
        rel_paths: list[Path] = []
        for m in matches:
            try:
                rel_paths.append(m.relative_to(runtime.project_root))
            except ValueError:
                continue

        # 过滤隐藏条目（任何以 "." 开头的段）。
        rel_paths = [p for p in rel_paths if not any(part.startswith(".") for part in p.parts)]

        if sort_by == "mtime":
            # 按底层文件的 mtime 排序，最新在前。我们解析回绝对路径
            # 来读 mtime —— pathlib 把 mtime 存在文件本身，而不是
            # 相对 Path 上。
            rel_paths.sort(
                key=lambda p: -(runtime.project_root / p).stat().st_mtime
            )
        else:  # "name" —— 默认；确定性、与 locale 无关的排序
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
