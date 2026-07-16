"""单轮派发运行时。

本包是所有写作能力运行时（单轮派发）的统一外观接口。状态机主类
:class:`writer.runner.Runner` 持有 ``RunnerDeps``（DI 容器）和
``RunnerConfig``（per-loop 配置）；会话级状态由调用方持有
（典型来源是 :class:`writer.session.Engine`）。
"""

from writer.runner.config import RunnerConfig, build_runner_config
from writer.runner.context import RunnerContext
from writer.runner.deps import RunnerDeps, production_deps
from writer.runner.events import (
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
from writer.runner.loop import run_runner
from writer.runner.runner import Runner

__all__ = [
    "ActionEvent",
    "Done",
    "DoneReason",
    "ErrorEvent",
    "Event",
    "Interrupt",
    "Runner",
    "RunnerConfig",
    "RunnerContext",
    "RunnerDeps",
    "TextChunk",
    "ToolCall",
    "ToolResult",
    "build_runner_config",
    "production_deps",
    "run_runner",
]
