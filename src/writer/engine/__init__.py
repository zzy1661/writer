"""Agent 引擎运行时。

本包是所有写作能力运行时的统一外观接口。状态机主类
:class:`writer.engine.Engine` 持有 ``EngineDeps``（DI 容器）和
``EngineConfig``（per-loop 配置）；会话级状态由调用方持有
（典型来源是 :class:`writer.session.EngineSession`）。
"""

from writer.engine.config import EngineConfig, build_engine_config
from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps, production_deps
from writer.engine.engine import Engine
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
    "Engine",
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
