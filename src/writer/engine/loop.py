"""引擎状态机的兼容层 shim（per 2026-07-13 ``Engine`` 类引入）。

**已迁移**：状态机实现已搬到 :mod:`writer.engine.engine` 的
:class:`writer.engine.Engine` 类。本模块保留 :func:`run_engine`
作为兼容 shim —— 接收 ``(ctx, deps)`` 参数并构造临时 ``Engine``
实例委派给 :meth:`Engine.run`。

新代码应直接使用 :class:`Engine`：

.. code-block:: python

    engine = Engine(deps=deps)
    async for event in engine.run(ctx):
        ...

历史：

Phase 2 接线（per 旧 docstring）：
* ``/大纲`` 的 ``run_command`` 通过 ``_run_directive`` 派发到 Markdown 范式
  的 agent 指令；LLM 消费指令 body 并使用 tool registry 写出大纲。
* ``write_chapter`` / ``review_chapter`` 通过 ``start_workflow`` 派发到
  :meth:`EngineDeps.run_workflow`。

Phase 3 接线（per change ``add-llm-and-complete-engine-loop``）：
* ``call_tool`` 通过 ``deps.tool_registry`` 解析工具，由 ``deps.tool_runtime``
  调用。
* ``ask_user`` 产出 ``Interrupt`` 让 REPL 可以提示用户。
* 所有异常（路由器、工具、工作流）都会被捕获，并以 ``ErrorEvent``
  后接 ``Done('aborted')`` 的形式暴露。

实现已迁至 :class:`writer.engine.Engine`，详见该类 docstring。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from writer.engine.config import EngineConfig
from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps
from writer.engine.engine import Engine
from writer.engine.events import (
    ActionEvent,
    Done,
    ErrorEvent,
    Interrupt,
    TextChunk,
    ToolCall,
    ToolResult,
)


async def run_engine(
    ctx: EngineContext,
    deps: EngineDeps,
    *,
    config: EngineConfig | None = None,
) -> AsyncIterator[
    TextChunk | ActionEvent | Interrupt | ToolCall | ToolResult | Done | ErrorEvent
]:
    """兼容 shim —— 构造临时 :class:`Engine` 实例委派给 :meth:`Engine.run`。

    新代码应直接持有 :class:`Engine` 实例（典型来源：
    :attr:`writer.session.EngineSession.engine`）并调用 ``engine.run(ctx)``。

    本 shim 仅用于一次性调用（如测试 stub、e2e pipe）—— 它每次都构造
    新的 ``Engine``，因此没有 rebind 缓存。
    """
    engine = Engine(deps=deps, cfg=config)
    async for event in engine.run(ctx):
        yield event


__all__ = ["run_engine"]
