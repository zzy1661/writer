"""单轮派发状态机。

:class:`Runner` 是 runner 层的主类 —— 持有 ``RunnerDeps``（DI 容器）与
``RunnerConfig``（per-loop 配置），并暴露 ``run(ctx)`` 作为每轮的
async generator 入口。

为什么这里有个 ``Runner`` 类（而不是一组自由函数）：

* 6 个 helper（``_run_*``）全都接收同样的 ``(action, ctx, deps, cfg)``
  参数，把这些状态抽到 ``self`` 上能消除重复参数传递。
* CLI 与 e2e 调用方只需要关心 ``runner.run(ctx)`` —— 不再关心 deps 与
  cfg 的内部接线。
* 把 ``Runner`` 视为**对象**（而非"runner 是个东西"这种抽象层名），
  让 ``RunnerDeps`` / ``RunnerContext`` / ``RunnerConfig`` 的命名
  真正对应到实体对象上（消除 ``RunnerDeps`` 命名里"Runner 对象存在吗"的歧义）。

Public API：
* ``run(ctx)`` —— 单轮入口，``AsyncIterator`` 产出 ``TextChunk`` /
  ``ActionEvent`` / ``Interrupt`` / ``ToolCall`` / ``ToolResult`` /
  ``Done`` / ``ErrorEvent``。
* ``replace_deps(new_deps)`` —— 返回新 ``Runner``（rebind 模式，
  与 ``RunnerDeps.rebind_*`` 对称）。

历史：

Phase 2 接线（per ``loop.py`` 旧 docstring）：
* ``/大纲`` 的 ``run_command`` 通过 ``_run_directive`` 派发到 Markdown 范式
  的 agent 指令；LLM 消费指令 body 并使用 tool registry 写出大纲。
* ``write_chapter`` / ``review_chapter`` 通过 ``start_workflow`` 派发到
  :meth:`RunnerDeps.run_workflow`。

Phase 3 接线（本类，per change ``add-llm-and-complete-engine-loop``）：
* ``call_tool`` 通过 ``self._deps.tool_registry`` 解析工具，由
  ``self._deps.tool_runtime`` 调用。
* ``ask_user`` 产出 ``Interrupt`` 让 REPL 可以提示用户，然后产出
  ``Done('ask_user')``。
* 所有异常（路由器、工具、工作流）都会被捕获，并以 ``ErrorEvent``
  后接 ``Done('aborted')`` 的形式暴露。``ErrorEvent.traceback``
  携带格式化堆栈。
* ``RunnerConfig.fast_mode`` 抑制诊断用的 ``[engine]`` 日志块。
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import AsyncIterator
from pathlib import Path

from writer.project import (
    ProjectState,
    create_workspace,
)
from writer.routing import AgentAction
from writer.runner.config import RunnerConfig
from writer.runner.context import RunnerContext
from writer.runner.deps import RunnerDeps
from writer.runner.events import (
    ActionEvent,
    Done,
    ErrorEvent,
    Interrupt,
    TextChunk,
    ToolCall,
    ToolResult,
)
from writer.skills import SkillDirective
from writer.skills.errors import SkillError
from writer.tools.errors import ToolError

log = logging.getLogger(__name__)


class Runner:
    """单轮派发状态机 —— 异步事件流生成器。

    拥有：
    - ``deps`` — :class:`writer.runner.deps.RunnerDeps`（长生命周期
      DI 容器；project_root 变更时通过 ``replace_deps`` 整体替换）。
    - ``cfg`` — :class:`writer.runner.config.RunnerConfig`（per-loop 配置，
      构造时初始化一次）。

    不拥有（per-turn 由调用方传入）：
    - ``ctx`` — :class:`RunnerContext`（单轮不可变输入）。
    """

    def __init__(
        self,
        deps: RunnerDeps,
        cfg: RunnerConfig | None = None,
    ) -> None:
        self._deps = deps
        self._cfg = cfg or RunnerConfig(session_id="")

    @property
    def deps(self) -> RunnerDeps:
        return self._deps

    @property
    def cfg(self) -> RunnerConfig:
        return self._cfg

    def replace_deps(self, new_deps: RunnerDeps) -> Runner:
        """返回一个新的 ``Runner``，``deps`` 已被替换。

        与 :meth:`RunnerDeps.rebind_*` 对称，用于
        :meth:`writer.session.Engine.set_project_root` 等
        需要整体替换依赖的场景。``cfg`` 保持不变（同一进程内的
        ``fast_mode`` 等配置不变）。
        """
        return Runner(deps=new_deps, cfg=self._cfg)

    def replace_cfg(self, new_cfg: RunnerConfig) -> Runner:
        """返回一个新的 ``Runner``，``cfg`` 已被替换。"""
        return Runner(deps=self._deps, cfg=new_cfg)

    async def run(
        self,
        ctx: RunnerContext,
    ) -> AsyncIterator[
        TextChunk
        | ActionEvent
        | Interrupt
        | ToolCall
        | ToolResult
        | Done
        | ErrorEvent
    ]:
        """单轮入口：派发一次，产出事件直至 ``Done``。

        ``ctx`` 由调用方构造（典型来源是
        :meth:`writer.session.Engine.run_turn`），作为不可变输入。
        """
        async for event in self._engine_loop(ctx):
            yield event

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _log(self, text: str) -> TextChunk:
        """诊断日志块；仅在 ``cfg.fast_mode`` 为 False 时产出。"""

        return TextChunk(text=text)

    async def _engine_loop(
        self,
        ctx: RunnerContext,
    ) -> AsyncIterator[
        TextChunk
        | ActionEvent
        | Interrupt
        | ToolCall
        | ToolResult
        | Done
        | ErrorEvent
    ]:
        """每轮内部循环：派发一次，然后产出 ``Done``。

        整体 body 被 ``try/except`` 包裹，让路由器、工具或工作流中
        出现意外失败时产出 ``ErrorEvent`` 后接 ``Done(aborted)``，而不是
        从 async generator 中冒泡出去。两个 except 分支都会把堆栈
        捕获进 ``ErrorEvent.traceback``（per arch-optimizer M4），
        让 REPL 输出可以直接贴进 bug report 而无需重跑引擎。
        """

        deps = self._deps
        cfg = self._cfg

        try:
            if not cfg.fast_mode:
                yield self._log(f"[engine] 分析输入: {ctx.user_input!r}\n")

            action = deps.route(ctx.user_input, ctx.project_state)
            yield ActionEvent(action=action)

            # per 2026-07-23: ``/init`` 不再走 explore brief 路径;
            # ``/init <故事梗概>`` 由 ``_run_init_command`` 拒绝并提示
            # 改用 ``/start``。``/init`` 唯一合法形式是 ``/init <项目名>``
            # (向后兼容 ``writer new <书名>``)。

            # 先按 ``action.kind`` 派发（per ``fea-agent-mirror``）——
            # ``kind="agent"`` 的 action 走 agent 路径，无论底层
            # ``action_type`` 是什么（LLM 可能发出 ``answer_directly``，
            # 因为 agent 通常以散文回答）。
            if action.kind == "agent":
                async for event in self._run_agent(action, ctx):  # type: ignore[assignment]
                    yield event
                return

            match action.action_type:
                case "answer_directly":
                    yield TextChunk(text=action.answer or "")
                    yield Done(reason="answered", payload={"answer": action.answer})

                case "run_command":
                    if action.command == "/init":
                        async for event in self._run_init_command(ctx):
                            yield event
                    elif action.command and (
                        directive := deps.directive_registry.get(action.command)
                    ) is not None:
                        # 动态派发：任何映射到已注册 Directive 的斜杠命令
                        # 都走 LLM 指令执行路径。新增 directive 无需触碰本分支；
                        # DirectiveRegistry 是唯一的真理来源。
                        if not cfg.fast_mode:
                            yield self._log(
                                f"[engine] {action.command} → directive "
                                f"({directive.command})\n",
                            )
                        async for event in self._run_directive(directive, ctx):  # type: ignore[assignment]
                            yield event
                    else:
                        if not cfg.fast_mode:
                            yield self._log(
                                f"[engine] 命令 {action.command} 待执行\n"
                            )
                        yield Done(
                            reason="command_pending",
                            payload={"command": action.command},
                        )

                case "call_tool":
                    if deps.tool_loop is not None:
                        # LLM 驱动的多步工具循环（ReAct 风格）。
                        # 循环观察 ``ToolResult`` 事件并可能继续调用工具，
                        # 直到模型发出 ``answer_directly`` 或预算耗尽。
                        # 纯规则部署（无 API key）保持 ``tool_loop = None``，
                        # 走同步 ``_run_tool`` 路径 —— 通用情况零 LLM 成本。
                        async for event in self._run_tool_loop(  # type: ignore[assignment]
                            action, ctx
                        ):
                            yield event
                    else:
                        async for event in self._run_tool(action):  # type: ignore[assignment]
                            yield event

                case "start_workflow":
                    async for event in self._run_workflow(  # type: ignore[assignment]
                        action.workflow or "", ctx
                    ):
                        yield event

                case "ask_user":
                    if not cfg.fast_mode:
                        yield self._log(
                            f"[engine] 需要用户补充: {action.user_prompt}\n"
                        )
                    prompt = action.user_prompt or "请补充信息"
                    yield Interrupt(type="text", prompt=prompt, options=None)
                    yield Done(reason="ask_user", payload={"prompt": prompt})

        except ToolError as exc:
            # ``ToolError`` 是领域异常（路径 / 权限 / 未找到工具 /
            # 未找到工作流）；捕获堆栈让用户能看到失败源自工具 / 工作流的
            # 哪个位置，而无需挂调试器。
            tb = traceback.format_exc()
            log.warning("工具错误: %s", exc, exc_info=True)
            yield ErrorEvent(message=f"工具错误: {exc}", traceback=tb)
            yield Done(reason="aborted", payload={"error": str(exc)})
        except SkillError as exc:
            # ``SkillError`` 是 Skill 侧的 ``ToolError`` 对等物：由 ``Skill.run``
            # 抛出，代表可恢复的失败（缺失 project root、前置条件未满足、
            # 参数格式错误）。附带被拒绝的命令，让 REPL 能渲染出有用的红色 ✗
            # 提示，告诉用户 *哪个* skill 失败。
            tb = traceback.format_exc()
            log.warning("技能错误: %s", exc, exc_info=True)
            # SkillError 本身不携带 skill command —— 从最近派发的 action 恢复，
            # 保持 payload 稳定。
            command = getattr(exc, "command", getattr(action, "command", None))
            yield ErrorEvent(message=f"技能错误: {exc}", traceback=tb)
            yield Done(
                reason="aborted",
                payload={"error": str(exc), "command": command},
            )
        except Exception as exc:  # noqa: BLE001 — Runner 边界绝不能抛
            tb = traceback.format_exc()
            log.exception("Runner 边界异常: %s", exc)
            yield ErrorEvent(message=f"Runner 异常: {exc}", traceback=tb)
            yield Done(reason="aborted", payload={"error": str(exc)})

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    async def _run_tool(
        self, action: AgentAction
    ) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
        """为 ``call_tool`` action 解析、调用并产出事件。"""

        deps = self._deps
        cfg = self._cfg

        name = action.tool_name or ""
        arguments = dict(action.arguments)

        if not cfg.fast_mode:
            yield TextChunk(text=f"[engine] 工具 {name} 调用中…\n")
        yield ToolCall(name=name, arguments=arguments)

        # 工具层自身的 try/except 位于 _engine_loop 之内，会捕获
        # ToolError；这里只是调用并让异常向外传播，由外层边界产生
        # ErrorEvent + Done(aborted)。
        result = deps.tool_registry.invoke(name, deps.tool_runtime, **arguments)
        yield ToolResult(name=name, output=result.output)

        if not cfg.fast_mode:
            yield TextChunk(text=f"[engine] 工具 {name} 完成\n")
        yield Done(
            reason="tool_completed",
            payload={"tool": name, "output": result.output},
        )

    async def _run_tool_loop(
        self, action: AgentAction, ctx: RunnerContext
    ) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
        """多步调用委托给 :class:`writer.llm.agent.ReActAgent`。

        前置条件：``self._deps.tool_loop is not None``（Runner 的
        ``case "call_tool"`` 分支只在这种情况下路由到这里）。

        循环内抛出的 ``ToolError`` 向外传播，让外层 ``_engine_loop`` 的
        ``except ToolError`` 分支产出与同步 ``_run_tool`` 一致的
        ``ErrorEvent + Done(aborted)`` UX —— 此接缝不做吞异常。
        """

        deps = self._deps
        cfg = self._cfg

        if deps.tool_loop is None:
            # 防御性：考虑到 Runner ``case "call_tool"`` 守卫，理论上走不到这里，
            # 但清晰的报错能让任何后续维护者一眼看清契约。
            msg = "_run_tool_loop called without deps.tool_loop"
            raise RuntimeError(msg)
        if not cfg.fast_mode:
            yield self._log(
                f"[engine] 进入 LLM 工具循环(action={action.action_type})\n"
            )
        async for event in deps.tool_loop.run(action, ctx, deps, cfg):
            yield event

    async def _run_workflow(
        self, name: str, ctx: RunnerContext
    ) -> AsyncIterator[TextChunk | Done]:
        """运行已注册的工作流并按其 :class:`WorkflowResult` 派发。

        将 ``result.status`` 映射为 ``DoneReason``：

        * ``"completed"`` → ``Done(reason="workflow_completed", payload=...)``，
          payload 中携带工作流的 ``artifacts``（路径转字符串）和
          ``metrics``，便于 CLI 渲染。
        * ``"failed"`` → ``Done(reason="aborted", payload={"workflow": name, "error": ...})``，
          让现有 Runner 边界的 aborted 分支以一致的方式处理错误 UX。
        * ``"pending"`` → ``Done(reason="aborted", payload={"workflow": name, "decision": "needs_rewrite"})``
          （PR3+）。PR1 中用于 ``workflow_pending`` 的弃用分支已移除；
          需要重写信号的工作流通过 ``status="pending"`` 表达，
          但 Runner 通过 ``aborted`` reason 暴露（附带 ``decision`` metric
          以便消费者区分"需要重写"和真实失败）。

        旧的 ``[engine] 工作流 X 启动`` 日志块在非 fast 模式下保留，
        以保持与原 stub 路径的诊断一致性。
        """

        deps = self._deps
        cfg = self._cfg

        if not cfg.fast_mode:
            yield TextChunk(text=f"[engine] 工作流 {name} 启动\n")
        result = deps.run_workflow(name, ctx)
        for chunk in result.chunks:
            yield TextChunk(text=chunk)
        if result.status == "completed":
            yield Done(
                reason="workflow_completed",
                payload={
                    "workflow": name,
                    "artifacts": {k: str(v) for k, v in result.artifacts.items()},
                    "metrics": dict(result.metrics),
                },
            )
            return
        if result.status == "pending":
            # PR3+：pending = 工作流产出了一个「需要上游动作」的信号
            # （例如 review_chapter 的 needs_rewrite）。Runner 以 ``aborted``
            # 暴露，附带 ``decision`` metric 让 REPL 能展示有用的提示。
            # ``workflow_pending`` 不再是合法的 ``DoneReason``。
            decision = str(result.metrics.get("decision", "needs_rewrite"))
            yield Done(
                reason="aborted",
                payload={
                    "workflow": name,
                    "decision": decision,
                    "artifacts": {k: str(v) for k, v in result.artifacts.items()},
                    "metrics": dict(result.metrics),
                },
            )
            return
        # status == "failed"
        error_msg = str(result.metrics.get("error", "")) or f"工作流 {name} 失败"
        yield Done(
            reason="aborted",
            payload={"workflow": name, "error": error_msg},
        )

    async def _run_agent(
        self, action: AgentAction, ctx: RunnerContext
    ) -> AsyncIterator[
        TextChunk | ActionEvent | Interrupt | ToolCall | ToolResult | Done | ErrorEvent
    ]:
        """将 ``kind="agent"`` action 派发给 LLM，注入 agent body。

        Per ``fea-agent-mirror`` Decision 7：Runner 组装一次 LLM 调用，
        其 system prompt 由所选 agent 的 ``body``（agent 的身份 / 角色描述）
        与题材特定的大纲模板拼接。LLM 通过现有的
        :class:`writer.llm.agent.ReActAgent` 路径调用（配置了 API key 时），
        让模型在产出结构化大纲前可用 tool registry 读取项目状态。

        没有 LLM 时（``deps.tool_loop is None``）helper 产出一段预览
        TextChunk 描述被选中的 agent（不生成真实大纲 —— 之前的
        ``writer.roles.StoryAgent._draft_outline_fallback`` 已在
        ``chg-remove-roles`` 中删除）。CLI 在终结 ``Done`` payload 中
        渲染 agent 名称，让用户看到是哪个 agent 产出了回答。

        错误：

        * :class:`writer.agents.AgentRegistryError` 由
          ``agent_registry.require`` 在 ``action.target_agent`` 不是已知
          agent 时抛出 → 由 Runner 边界捕获，以
          ``ErrorEvent + Done(aborted, payload={"error": ..., "command": name})``
          暴露。
        * 其他 LLM / 工具失败由外层 ``_engine_loop`` 边界
          （``except Exception`` 分支）捕获。
        """

        from writer.agents import AgentRegistryError  # noqa: PLC0415

        deps = self._deps
        cfg = self._cfg

        agent_name = action.target_agent or ""
        try:
            agent = deps.agent_registry.require(agent_name)
        except AgentRegistryError as exc:
            # 把决策让给 Runner 边界的现有 ``except`` 分支：原计划是重抛为
            # ``ToolError`` 形态的 ``AgentRegistryError``；但由于
            # ``AgentRegistryError`` 是 ``ValueError``（不是 ``ToolError``），
            # 我们改为直接产出事件，避免边界的 catch-all 分支重复包装消息。
            tb_msg = str(exc)
            log.warning("Agent dispatch 错误: %s", exc, exc_info=True)
            yield ErrorEvent(message=f"Agent 错误: {exc}", traceback=tb_msg)
            yield Done(
                reason="aborted",
                payload={"error": str(exc), "command": agent_name},
            )
            return

        if not cfg.fast_mode:
            yield self._log(f"[engine] agent dispatch → {agent_name}\n")

        if deps.tool_loop is not None:
            # LLM 驱动路径：把 agent body 喂给现有工具循环，
            # 它已经知道如何用结构化输出 schema 和 tool registry 调用 LLM。
            # 借力 ``answer_directly`` 让循环只产出散文；
            # agent body 是 system identity，用户输入是 human message。
            agent_action = AgentAction(
                action_type="answer_directly",
                command=None,
                kind="agent",
                target_agent=agent_name,
                answer=(
                    f"[agent {agent_name!r} system identity]\n"
                    f"{agent.body}\n"
                    f"\n[user input]\n{ctx.user_input}"
                ),
            )
            async for event in deps.tool_loop.run(agent_action, ctx, deps, cfg):
                yield event
        else:
            # 没有可用 LLM —— 产出 agent body 作为预览，让用户看到选中
            # 的 agent 以及它的身份。这与 Runner 其他地方使用的纯规则
            # 回退路径一致（``_run_directive``）。
            yield TextChunk(
                text=(
                    f"[agent {agent_name!r} preview, no LLM configured]\n"
                    f"  name: {agent.name}\n"
                    f"  genre: {agent.genre}\n"
                    f"  body length: {len(agent.body)} chars\n"
                    f"  description: {agent.description}\n"
                )
            )
            yield Done(
                reason="answered",
                payload={
                    "agent": agent_name,
                    "genre": agent.genre,
                    "body_length": len(agent.body),
                    "llm_available": False,
                },
            )

    async def _run_directive(
        self, directive: SkillDirective, ctx: RunnerContext
    ) -> AsyncIterator[TextChunk | Done | ToolCall | ToolResult]:
        """通过 LLM 工具循环执行 Markdown SKILL.md directive。

        directive 的 body 是给 LLM 的指令文本。本 helper 解析 body 中的
        ``@reference path/to/file.md`` 引用并暴露给 LLM，让它能读取相关
        引用资料。LLM 消化指令后，驱动现有 tool registry
        （``safe_read_file``、``safe_write_file`` 等）完成实际工作。

        实现状态（per chg-markdown-skills spec）：
        * Body + 解析后的引用通过现有 ``deps.tool_loop.run`` 路径注入
          LLM 上下文，该路径已处理 JSON 动作协议与工具派发。
        * Directive 的元数据（``command`` / ``description``）
          通过 ``TextChunk`` 输出给用户，便于透明。
        * 若 ``deps.tool_loop`` 为 ``None``（纯规则部署），
          helper 降级为只输出 TextChunk 的 stub，打印 directive body
          摘要 —— 没有 API key 时无法真正执行 LLM。
        """

        deps = self._deps
        cfg = self._cfg

        if not cfg.fast_mode:
            yield TextChunk(
                text=f"[engine] {directive.command} → directive ({directive.command})\n"
            )

        # 把 ``@reference path`` 提及解析为 (相对路径, 内容) 对。
        # 本地 import 以避免模块加载时的循环 import
        # （directive_discovery 已经从 skills.registry import）。
        from writer.skills.directive_discovery import resolve_references  # noqa: PLC0415

        resolved = resolve_references(directive.body, directive.references)

        if deps.tool_loop is not None:
            # 把 directive + 解析后的引用交给现有 LLM 工具循环。
            # 循环读取 action 的 body 和 references，然后驱动 tool registry。
            from writer.routing import AgentAction  # noqa: PLC0415

            action = AgentAction(
                action_type="answer_directly",
                command=directive.command,
                answer=directive.body,
            )
            # 把解析后的引用暂存到临时属性，便于循环读取；
            # 循环的契约由 answer 字段携带的 directive body 满足。
            # NOTE: 未来任务可能通过专用的 directive-aware 循环子类
            # 接入 ``resolved``。
            async for event in deps.tool_loop.run(action, ctx, deps, cfg):
                yield event
        else:
            # 没有可用 LLM —— 产出有用的预览，让用户看到 directive 本应做什么。
            yield TextChunk(
                text=(
                    f"[engine] directive body (preview, no LLM configured):\n"
                    f"  command: {directive.command}\n"
                    f"  description: {directive.description}\n"
                    f"  body length: {len(directive.body)} chars\n"
                    f"  references: {len(resolved)} files\n"
                    f"  scripts: {len(directive.scripts)} files\n"
                )
            )
            if resolved:
                preview = "\n".join(
                    f"  ref: {relpath} ({len(content)} chars)"
                    for relpath, content in resolved
                )
                yield TextChunk(text=preview + "\n")
            yield Done(
                reason="answered",
                payload={
                    "directive": directive.command,
                    "body_length": len(directive.body),
                    "references": [relpath for relpath, _ in resolved],
                    "scripts": list(directive.scripts),
                    "llm_available": False,
                },
            )

    # ------------------------------------------------------------------
    # /init 派发
    # ------------------------------------------------------------------

    async def _run_init_command(
        self,
        ctx: RunnerContext,
    ) -> AsyncIterator[TextChunk | Done]:
        """处理 ``/init <项目名>``(向后兼容 ``writer new <书名>``)。

        per 2026-07-23: ``/init`` 只生成基础目录/文件,不再接受故事
        梗概作为参数(那是 ``/start`` 的职责)。``/init <创意>`` 形式
        会被拒绝并提示用户改用 ``/start`` —— 用户应该先把核心创意
        写到 ``创意/简介.md``,然后跑 ``/start``。
        """

        cfg = self._cfg

        rest = ctx.user_input.removeprefix("/init").strip()

        # 拒绝「看起来像 brief」的输入:含中文/西文标点(句号/逗号),
        # 或长度 > 30 字。短 token 仍按项目名处理(向后兼容)。
        if rest and (
            "。" in rest
            or "，" in rest
            or "," in rest
            or len(rest) > 30
        ):
            msg = (
                "/init 现在只生成基础目录/文件。"
                "如需启动创作,请编辑 创意/简介.md 后运行 /start。"
            )
            yield TextChunk(text=f"{msg}\n")
            yield Done(reason="aborted", payload={"command": "/init", "error": msg})
            return

        if not rest:
            msg = "用法：/init <项目名>。例如：/init 我的小说"
            yield TextChunk(text=f"{msg}\n")
            yield Done(reason="aborted", payload={"command": "/init", "error": msg})
            return

        if not cfg.fast_mode:
            yield TextChunk(text="[engine] /init → create_workspace\n")

        workspace = create_workspace(rest, Path("."))
        yield TextChunk(text=f"已初始化项目: {workspace.root}\n")
        yield Done(
            reason="answered",
            payload={
                "command": "/init",
                "project_root": str(workspace.root.resolve()),
                "project_state": ProjectState.INITIALIZED.value,
            },
        )


__all__ = ["Runner"]
