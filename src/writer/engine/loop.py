"""Engine main loop.

The engine is a *stateless* ``AsyncGenerator``: callers (REPL, future
``EngineSession``) own the per-session state and re-invoke ``run_engine``
each turn. The benefits over a single ``run() -> Result`` mirror Claude
Code §一·1.2: streaming output, late-binding decisions, and clean
cancellation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from writer.engine.config import EngineConfig, build_engine_config
from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps
from writer.engine.events import ActionEvent, Done, TextChunk


async def run_engine(
    ctx: EngineContext,
    deps: EngineDeps,
    *,
    config: EngineConfig | None = None,
) -> AsyncIterator[TextChunk | ActionEvent | Done]:
    """Public entry point. Wraps ``_engine_loop`` for future hooks."""

    cfg = config or build_engine_config(ctx)
    async for event in _engine_loop(ctx, deps, cfg):
        yield event


async def _engine_loop(
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | ActionEvent | Done]:
    """Per-turn inner loop: dispatch once, then yield ``Done``.

    MVP scope: every action type short-circuits to a terminal ``Done``.
    Subsequent turns will introduce ``continue`` sites that route the
    action through LangGraph workflows / Tool registry / interrupt
    handlers before terminating.
    """

    yield TextChunk(text=f"[engine] 分析输入: {ctx.user_input!r}\n")
    action = deps.decide(ctx.user_input, ctx.project_state)
    yield ActionEvent(action=action)

    match action.action_type:
        case "answer_directly":
            yield TextChunk(text=action.answer or "")
            yield Done(reason="answered", payload={"answer": action.answer})

        case "run_command":
            yield TextChunk(text=f"[engine] 命令 {action.command} 待执行")
            yield Done(reason="command_pending", payload={"command": action.command})

        case "call_tool":
            yield TextChunk(text=f"[engine] 工具 {action.tool_name} 待调用")
            yield Done(reason="tool_pending", payload={"tool": action.tool_name})

        case "start_workflow":
            yield TextChunk(text=f"[engine] 工作流 {action.workflow} 待启动")
            yield Done(reason="workflow_pending", payload={"workflow": action.workflow})

        case "ask_user":
            yield TextChunk(text=f"[engine] 需要用户补充: {action.user_prompt}")
            yield Done(reason="ask_user", payload={"prompt": action.user_prompt})


__all__ = ["run_engine"]
