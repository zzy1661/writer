"""Session layer — cross-turn state container.

EngineSession is the only owner of cross-turn state (session_id, deps,
turn history, pending Interrupt). It is constructed once at REPL start
and reused for every turn. The Engine Loop itself remains a stateless
AsyncGenerator (per 备忘 16 §"Engine 是无状态 AsyncGenerator").
"""

from writer.session.engine_session import EngineSession, TurnRecord, compose_pending_input

__all__ = ["EngineSession", "TurnRecord", "compose_pending_input"]
