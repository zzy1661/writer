"""单次 Runner 轮次的冻结环境快照。"""

from __future__ import annotations

from dataclasses import dataclass

from writer.runner.context import RunnerContext


@dataclass(frozen=True)
class RunnerConfig:
    """单轮内一次性捕获的不可变运行时配置。

    与 Claude Code §八「环境冰封」一致：配置在轮次内不会变动，
    消费者在解释事件流时可以放心依赖其中的值。
    """

    session_id: str
    fast_mode: bool = False


def build_runner_config(
    ctx: RunnerContext, *, fast_mode: bool = False
) -> RunnerConfig:
    """从上下文与运行时覆盖项快照出 Runner 配置。"""

    return RunnerConfig(session_id=ctx.session_id, fast_mode=fast_mode)


__all__ = ["RunnerConfig", "build_runner_config"]
