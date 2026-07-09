"""单次引擎轮次的冻结环境快照。"""

from __future__ import annotations

from dataclasses import dataclass

from writer.engine.context import EngineContext


@dataclass(frozen=True)
class EngineConfig:
    """单轮内一次性捕获的不可变运行时配置。

    与 Claude Code §八「环境冰封」一致：配置在轮次内不会变动，
    消费者在解释事件流时可以放心依赖其中的值。
    """

    session_id: str
    fast_mode: bool = False


def build_engine_config(
    ctx: EngineContext, *, fast_mode: bool = False
) -> EngineConfig:
    """从上下文与运行时覆盖项快照出引擎配置。"""

    return EngineConfig(session_id=ctx.session_id, fast_mode=fast_mode)


__all__ = ["EngineConfig", "build_engine_config"]
