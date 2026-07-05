"""Agent engine runtime.

This package is the runtime facade for every writing capability. It is
deliberately stateless (``AsyncGenerator`` per turn); per-session state
is owned by the caller (REPL today, ``EngineSession`` tomorrow).
"""

from writer.engine.config import EngineConfig, build_engine_config
from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps, production_deps
from writer.engine.events import (
    ActionEvent,
    Done,
    DoneReason,
    ErrorEvent,
    Event,
    Interrupt,
    TextChunk,
    ToolCall,
    ToolResult,
)
from writer.engine.loop import run_engine

__all__ = [
    "ActionEvent",
    "Done",
    "DoneReason",
    "EngineConfig",
    "EngineContext",
    "EngineDeps",
    "ErrorEvent",
    "Event",
    "Interrupt",
    "TextChunk",
    "ToolCall",
    "ToolResult",
    "build_engine_config",
    "production_deps",
    "run_engine",
]
