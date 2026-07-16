"""Runner 的依赖注入边界。

Runner 从不直接实例化协作者——所有外部边界都以 ``Protocol`` 在此处声明。
这与 Claude Code §十「最小接口 DI」一致：只注入会被替换的部分
（测试、备用路由器、未来 LLM 实现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from writer.agents import AgentRegistry, built_agent_registry
from writer.config import Settings, get_settings
from writer.routing import (
    AgentAction,
    CompositeRouter,
    IntentRouter,
    LlmIntentRouter,
    RuleBasedIntentRouter,
)
from writer.skills import DirectiveRegistry, built_directive_registry
from writer.tools import ToolRegistry, ToolRuntime, built_tool_registry
from writer.tools.errors import WorkflowNotFoundError
from writer.workflows import WORKFLOWS, WorkflowResult, WorkflowStub

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from writer.llm.agent import ReActAgent
    from writer.llm.prose import LLMProseClient
    from writer.runner.context import RunnerContext

# 未初始化项目（S0 路径）时使用的哨兵 project_root。
# 需要文件访问的工具会在 safe_path 检查处失败；
# 不需要路径的工具（foreshadow_search / chapter_locate / wordcount）仍可工作。
_NO_PROJECT_ROOT = Path("/__no_project__")


@runtime_checkable
class RunnerDeps(Protocol):
    """Runner 循环所依赖的最小表面。

    当前字段：

    * :attr:`router` — 前台派发器（per 备忘 15；Protocol
      :class:`writer.routing.IntentRouter`）。
    * :attr:`agent_registry` — :class:`writer.agents.AgentRegistry`，
      负责把 agent 名称解析为 YAML 加载的定义。Project 切换时通过
      :meth:`rebind_agent_registry` 重建（per ``fea-agent-mirror``）。
    * :attr:`tool_registry` — :class:`writer.tools.ToolRegistry`，
      负责把工具名称解析为实现（per 备忘 13）。
    * :attr:`tool_runtime` — :class:`writer.tools.ToolRuntime`，
      携带每次工具调用都会经过的会话级守卫。
    * :attr:`tool_loop` — 可选 ReAct 风格的 LLM 工具循环。仅规则部署
      （无 API key）时为 ``None``，Runner 仍可通过 ``_run_tool`` 工作
      而零 LLM 调用；配置 API key 时填充。以字符串前向引用，避免
      runner 包对 ``writer.llm.*`` 的直接 import。
    * :attr:`directive_registry` — :class:`writer.skills.DirectiveRegistry`，
      将斜杠命令映射到 :class:`writer.skills.SkillDirective`
      （Markdown SKILL.md 指令）。Project 切换时通过
      :meth:`rebind_directive_registry` 重建（per ``chg-markdown-skills``）。

    ``story_agent`` 已在 ``chg-remove-roles``（2026-07-09）中移除：
    四个 ``*Agent`` Python 类在 ``fea-agent-mirror`` 把面向 LLM 的身份
    迁移到 Markdown 之后就已成为死代码；唯一幸存的 Python-side 能力
    （``process_init_brief``）直接读取 ``Settings``，不需要 per-role 实例。

    未来扩展点（暂不声明）：
    * ``workflow_starter``：更丰富的异步工作流入口（per 备忘 04；
      当前 sync 的 ``run_workflow`` 是 MVP 桥接）
    * ``interrupt_handler``：InterruptHandler（per 备忘 14）
    * ``stop_hooks``：StopHookRegistry（Claude Code §十二·12.3）
    """

    router: IntentRouter
    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    directive_registry: DirectiveRegistry
    tool_loop: ReActAgent | None
    prose_client: LLMProseClient | None
    # review LLM 的可选覆盖。设置后，``write_chapter`` 在结构化
    # ReviewVerdict 调用中使用此 LLM，而不是从 settings 重新构造
    # ``ChatOpenAI``。测试在此注入 recording fake；生产保持 None。
    review_llm: BaseChatModel | None
    # 全局配置；用于 tool_loop rebind 时复用同一 settings（2026-07-09
    # 增补以修复 Bug 01）。
    settings: Settings

    def route(self, user_input: str, project_state: str) -> AgentAction:
        ...

    def run_workflow(self, name: str, ctx: RunnerContext) -> WorkflowResult:
        ...

    def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> RunnerDeps:
        """返回一个新的（或就地变更后的） ``RunnerDeps``，其中 runtime 已替换。

        由 :meth:`writer.session.Engine.set_project_root` 调用，
        让既有 deps 指向新的 project root 而无需重建 router / tool_registry。
        实现可以自由返回新实例（默认实现用 ``dataclasses.replace``）
        或就地变更 ``self`` ——只要返回值作为新的 deps 使用，两种都合法。

        2026-07-05 增补以修复 arch-optimizer M6：原代码用鸭子类型
        ``is_dataclass(self.deps) and any(f.name == ...)``，
        在测试注入非 dataclass 的 ``RunnerDeps`` 实现时立刻失败。
        """
        ...

    def rebind_skill_registry(
        self, new_registry: DirectiveRegistry
    ) -> RunnerDeps:
        """返回一个新的（或就地变更后的） ``RunnerDeps``，其中 directive registry 已替换。

        与 :meth:`rebind_tool_runtime` 对称。由
        :meth:`writer.session.Engine.set_project_root` 在扫描新
        项目的 ``.writer/skills/`` 之后调用 —— 必须在 project 切换时重建，
        才能让项目级 directive 覆盖（per ``chg-markdown-skills``）
        在下一个 REPL 轮次生效。

        保留为 :meth:`rebind_directive_registry` 的别名，以兼容下游
        仍在使用旧名的代码。

        2026-07-08 与 project-skills 能力同期增补。2026-07-09
        （chg-markdown-skills）更名为 :meth:`rebind_directive_registry`。
        """
        ...

    def rebind_directive_registry(
        self, new_registry: DirectiveRegistry
    ) -> RunnerDeps:
        """返回一个新的（或就地变更后的） ``RunnerDeps``，其中 directive registry 已替换。

        与 :meth:`rebind_tool_runtime` 对称。由
        :meth:`writer.session.Engine.set_project_root` 在扫描新
        项目的 ``.writer/skills/`` 之后调用 —— 必须在 project 切换时重建，
        才能让项目级 directive 覆盖（per ``chg-markdown-skills``）
        在下一个 REPL 轮次生效。

        2026-07-09（chg-markdown-skills）增补。原先的
        :meth:`rebind_skill_registry` 保留为别名。
        """
        ...

    def rebind_agent_registry(
        self, new_registry: AgentRegistry
    ) -> RunnerDeps:
        """返回一个新的（或就地变更后的） ``RunnerDeps``，其中 agent registry 已替换。

        与 :meth:`rebind_directive_registry` 对称。由
        :meth:`writer.session.Engine.set_project_root` 在扫描新
        项目的 ``.writer/agents/`` 之后调用 —— 必须在 project 切换时重建，
        才能让项目级 agent 覆盖（per ``fea-agent-mirror``）
        在下一个 REPL 轮次生效。

        2026-07-09（``fea-agent-mirror``）增补。
        """
        ...

    def rebind_tool_loop(
        self, new_loop: ReActAgent | None
    ) -> RunnerDeps:
        """返回一个新的（或就地变更后的） ``RunnerDeps``，其中 ReAct 工具循环已替换。

        与 :meth:`rebind_tool_runtime` 对称。由
        :meth:`writer.session.Engine.set_project_root` 在替换
        ``tool_runtime`` 之后调用 —— 新的循环必须针对新的 runtime 构造，
        才能让 ``self._runtime`` 指向新的项目根。传 ``None`` 保持
        session 在 rule-only 模式（无 API key）。实现可以自由返回新
        实例（默认实现用 ``dataclasses.replace``）或就地变更 ``self``。

        2026-07-09 增补以修复 Bug 01（tool_loop 未在 project 切换时重建）。
        """
        ...


@dataclass
class _DefaultRunnerDeps:
    """使用规则路由器与内置工作流的生产装配。

    用 dataclass 而非手写类实现，是为了以后新增字段（tool registry、
    真正的工作流启动器…）只需一行改动而无需重写构造函数。
    """

    router: IntentRouter
    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    directive_registry: DirectiveRegistry
    tool_loop: ReActAgent | None = None
    prose_client: LLMProseClient | None = None
    review_llm: BaseChatModel | None = None
    settings: Settings = field(default=None)  # type: ignore[assignment]
    _workflows: dict[str, WorkflowStub] = field(default_factory=dict)

    def route(self, user_input: str, project_state: str) -> AgentAction:
        return self.router.route(user_input, project_state)

    def run_workflow(self, name: str, ctx: RunnerContext) -> WorkflowResult:
        runner = self._workflows.get(name)
        if runner is None:
            # 作为领域异常抛出（per arch-optimizer m18），让 Runner
            # ``_engine_loop`` 中的 ``except ToolError`` 分支将其作为
            # ``ErrorEvent`` 暴露，而不是假装未知名称产生了合法工作流块。
            available = sorted(self._workflows)
            raise WorkflowNotFoundError(
                f"未知工作流 {name!r}; available: {available}"
            )
        # 默认装配派发到包级的
        # :func:`writer.workflows.run_workflow` 适配器，它会检查已注册
        # 可调用对象的签名并传入 ``deps``（本实例）给 PR2+ 工作流。
        # 该适配器还会把任何遗留的 ``Iterable[str]`` 返回包装为
        # :class:`WorkflowResult`。
        from writer.workflows import run_workflow as _run_workflow_dispatch

        return _run_workflow_dispatch(name, ctx, self)

    def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> RunnerDeps:
        # 使用 ``dataclasses.replace`` 让生产装配保持事实上的不可变；
        # 需要变更的测试可以覆写本方法。
        return replace(self, tool_runtime=new_runtime)

    def rebind_skill_registry(
        self, new_registry: DirectiveRegistry
    ) -> RunnerDeps:
        # 向后兼容别名：per chg-markdown-skills，规范名为
        # ``rebind_directive_registry``，但旧的测试 stub 可能仍在调用旧名。
        return replace(self, directive_registry=new_registry)

    def rebind_directive_registry(
        self, new_registry: DirectiveRegistry
    ) -> RunnerDeps:
        # 与 ``rebind_tool_runtime`` 对称；使用 ``dataclasses.replace``
        # 保持生产装配事实上的不可变。Per chg-markdown-skills：
        # 项目级 directive 位于项目目录内，因此绑定项目变更时必须调用本方法。
        return replace(self, directive_registry=new_registry)

    def rebind_agent_registry(
        self, new_registry: AgentRegistry
    ) -> RunnerDeps:
        # 与 ``rebind_directive_registry`` 对称；使用
        # ``dataclasses.replace`` 保持生产装配事实上的不可变。
        # Per ``fea-agent-mirror``：项目级 agent 位于项目目录内，
        # 因此绑定项目变更时必须调用本方法。
        return replace(self, agent_registry=new_registry)

    def rebind_tool_loop(
        self, new_loop: ReActAgent | None
    ) -> RunnerDeps:
        # 与 ``rebind_tool_runtime`` 对称；2026-07-09 增补以修复 Bug 01：
        # set_project_root 时必须用新 runtime 重建 tool_loop，
        # 否则 ReActAgent._runtime 仍指向旧 project_root。
        return replace(self, tool_loop=new_loop)


def _select_router(
    settings: Settings,
    *,
    primary: IntentRouter | None = None,
    agent_registry: AgentRegistry | None = None,
) -> IntentRouter:
    """在配置了 API key 时返回 ``CompositeRouter``，否则返回纯规则路由器。

    ``primary`` 让调用者（尤其是测试）可以注入自定义规则路由器而无需
    重写本工厂；默认新建一个 :class:`RuleBasedIntentRouter`。
    2026-07-05 按 arch-optimizer M5 增补：原代码把
    ``RuleBasedIntentRouter()`` 硬编码在工厂内部，未来出现
    "RuleBasedIntentRouterV2" 时会被静默错过装配。

    ``agent_registry``（2026-07-09 按 ``fea-agent-mirror`` 增补）会
    透传给 LLM 路由器，让它的 system prompt 可以包含父 LLM 派发所需的
    可用 agent 列表。基于规则的路由器忽略它（规则仅处理斜杠命令）。
    """

    rule = primary or RuleBasedIntentRouter()
    if settings.has_api_key:
        return CompositeRouter(
            primary=rule,
            fallback=LlmIntentRouter(settings, agent_registry=agent_registry),
        )
    return rule


def production_deps(
    settings: Settings | None = None,
    *,
    project_root: Path | None = None,
    primary_router: IntentRouter | None = None,
    agent_registry: AgentRegistry | None = None,
) -> RunnerDeps:
    """REPL 与测试使用的默认依赖装配。

    纯工厂：不在调用方背后做文件系统 IO。

    测试可以显式传入 :class:`writer.config.Settings` 以避免全局
    配置查找；生产调用方（REPL、CLI）保持 ``None``，回退到
    :func:`writer.config.get_settings`。

    Args:
        settings: 全局配置的覆盖（主要用于测试）。
        project_root: tool runtime root 的可选覆盖。为 ``None``
            （S0 路径）时使用哨兵 root，让 ``safe_path`` 仍能拒绝越界；
            不需要路径的工具（``foreshadow_search`` 等）继续可用。
            也会传给 :func:`writer.skills.built_skill_registry`，
            让初始 skill registry 已反映已绑定项目 ``.writer/skills/``
            的覆盖（per ``chg-project-skills``）；同时传给
            :func:`writer.agents.built_agent_registry` 处理
            ``.writer/agents/`` 层（per ``fea-agent-mirror``）。
        primary_router: 在 ``CompositeRouter`` 中作为主路由器
            （配置了 API key 时）或作为独立路由器（未配置时）的
            可选覆盖。默认新建一个 :class:`RuleBasedIntentRouter`。
            2026-07-05 按 M5 增补。
        agent_registry: agent registry 的可选覆盖。默认是
            :func:`writer.agents.built_agent_registry` 限定到
            ``project_root``。2026-07-09 按 ``fea-agent-mirror`` 增补。

    在 ``chg-remove-roles``（2026-07-09）中删除：
        * ``story_agent=`` kwarg —— ``writer.roles.StoryAgent`` 及其三个
          子类已删除；``RunnerDeps.story_agent`` 是唯一消费者。
        * ``genre=`` kwarg —— 由已删除的 ``_agent_for_genre`` 工厂使用；
          唯一幸存的消费者（``Engine.refresh_project_genre``）
          在 session 构造 deps 之前自行读取 ``AGENT.md``。
    """

    resolved = settings if settings is not None else get_settings()
    root = (project_root or _NO_PROJECT_ROOT).resolve()
    tool_registry = built_tool_registry()
    tool_runtime = ToolRuntime(project_root=root)
    tool_loop: ReActAgent | None = None
    if resolved.has_api_key:
        # 延迟 import：纯规则部署（无 API key）永不加载 LLM 客户端栈；
        # runner 包也不对 ``writer.llm.agent`` 产生运行时依赖。
        # :class:`RunnerDeps.tool_loop` 中的前向引用使 mypy 在类型
        # 检查时也不需要 import 该模块。
        from writer.llm.agent import ReActAgent

        tool_loop = ReActAgent(
            settings=resolved,
            registry=tool_registry,
            runtime=tool_runtime,
        )

    # 解析 prose client。始终填充（永不为 None）：配置了 API key 时装配
    # Real 变体，否则是 Deterministic 变体。``production_deps`` 是唯一
    # 决定使用哪一个的地方 —— runner / workflow 代码根据
    # ``deps.prose_client.name``（``"real"`` vs ``"deterministic"``）
    # 分支，而不是判断是否存在 API key。Per real-writing-pipeline PR2。
    from writer.llm.prose import (
        DeterministicProseClient,
        RealProseClient,
    )

    if resolved.has_api_key:
        from writer.llm.provider import get_llm as _get_llm

        prose_client: LLMProseClient = RealProseClient(llm=_get_llm(resolved))
    else:
        prose_client = DeterministicProseClient()

    # 解析 agent registry：调用方显式传入优先，否则从 project_root
    # 构建（project_root 回退到 S0 哨兵；loader 把缺失目录视为「无项目层」）。
    resolved_agent_registry = (
        agent_registry
        if agent_registry is not None
        else built_agent_registry(project_root=root)
    )

    return _DefaultRunnerDeps(
        router=_select_router(
            resolved,
            primary=primary_router,
            agent_registry=resolved_agent_registry,
        ),
        agent_registry=resolved_agent_registry,
        tool_registry=tool_registry,
        tool_runtime=tool_runtime,
        directive_registry=built_directive_registry(project_root=root),
        tool_loop=tool_loop,
        prose_client=prose_client,
        settings=resolved,
        _workflows=dict(WORKFLOWS),
    )


__all__ = ["RunnerDeps", "production_deps"]
