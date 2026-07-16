"""Runner 的输入契约。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunnerContext:
    """单次 Runner 轮次的不可变输入。

    与 Claude Code 的每轮 ``Context`` 契约一致：Runner 在单轮内不会
    跨出本对象去取输入。``project_root`` 在 S0（无项目）路径下
    保持可选；``project_state`` 在真正的状态机接入前先以字符串
    占位。
    """

    user_input: str
    project_root: Path | None = None
    project_state: str = "S0"
    session_id: str = ""


__all__ = ["RunnerContext"]
