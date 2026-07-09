"""会话层 —— 跨轮次状态容器。

EngineSession 是跨轮次状态（session_id、deps、轮次历史、待处理 Interrupt）
的唯一持有者。它在 REPL 启动时构造一次，并在每轮复用。Engine Loop
本身仍然是 ``AsyncGenerator``（per 备忘 16 §"Engine 是无状态 AsyncGenerator"）。
"""

from writer.session.engine_session import EngineSession, TurnRecord, compose_pending_input

__all__ = ["EngineSession", "TurnRecord", "compose_pending_input"]
