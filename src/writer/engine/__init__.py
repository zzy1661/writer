"""Agent 引擎运行时。

本包是所有写作能力运行时的统一外观接口。它被刻意设计为无状态
（每轮一个 ``AsyncGenerator``）；会话级状态由调用方持有
（当前是 REPL，未来是 ``EngineSession``）。
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
