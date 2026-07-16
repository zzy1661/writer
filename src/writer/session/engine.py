"""跨轮次会话状态容器。

``Engine``（原 ``EngineSession``）在 REPL 启动时构造一次，并在每轮复用。它持有：

- **身份**（冻结）：``session_id``（UUID）和 ``started_at``（datetime）。
- **项目上下文**（可变）：``project_root``（Path | None）和从磁盘
  检测到的最新状态。
- **runner**（可变）：:class:`writer.runner.Runner` 实例，构造时
  一次性构建。``set_project_root`` 通过 :meth:`Runner.replace_deps`
  整体替换 runner 内部的 deps，保持 router / tool_registry /
  cfg 不变的前提下换掉 ``tool_runtime`` + ``tool_loop`` +
  ``directive_registry`` + ``agent_registry``。
- **turns**（可变）：仅追加的 :class:`TurnRecord` 列表。
- **pending_interrupt**（可变）：Runner 产出的最近一个 ``Interrupt`` 事件，
  在下一轮完成时清空。

Engine 并*不*替代每轮的 ``RunnerContext`` —— 后者保持不变，
作为 :meth:`Runner.run` 的不可变输入契约。Engine 位于 runner*外部*，
每轮喂给 runner 一个 context。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from writer.runner.events import (
        ActionEvent,
        Done,
        DoneReason,
        ErrorEvent,
        Interrupt,
        TextChunk,
        ToolCall,
        ToolResult,
    )
    from writer.runner.runner import Runner


@dataclass(frozen=True)
class TurnRecord:
    """一轮的结局：用户说了什么，runner 如何结束。"""

    turn_index: int
    user_input: str
    done_reason: DoneReason
    timestamp: datetime


_SENTINEL_PROJECT_ROOT = Path("/__no_project__")


@dataclass
class Engine:
    """跨轮次会话状态容器（per 备忘 16 line 374 reservation）。"""

    # 冻结的身份 —— 构造时设置一次，永不修改。
    session_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    # 项目上下文（可变）。
    project_root: Path | None = None
    project_state: str = "S0"
    project_genre: str = "other"

    # Runner —— 构造时构建一次；project_root 变更时通过
    # ``runner.replace_deps(new_deps)`` 替换内部 deps。
    runner: Runner | None = field(default=None)  # type: ignore[assignment]

    # 仅追加的轮次历史。
    turns: list[TurnRecord] = field(default_factory=list)

    # 上一轮的待处理 Interrupt；消费后清空。
    pending_interrupt: Interrupt | None = None

    def __post_init__(self) -> None:
        # 延迟 import 以避免循环 import（runner.runner 引入
        # writer.routing 等较重模块，按需加载）。
        if self.runner is None:
            from writer.runner.deps import production_deps
            from writer.runner.runner import Runner

            if self.project_root is not None:
                # 刷新 ``project_genre`` 让首次 ``/状态`` 读到正确值；
                # ``production_deps`` 本身不再读取 ``AGENT.md``
                # （per ``chg-remove-roles``）。
                self.refresh_project_genre()
            # ``production_deps`` 同时负责把 ``directive_registry`` 与
            # 已绑定项目接线（per chg-markdown-skills），让首次 ``/大纲`` 等
            # 查找能看到项目级覆盖。我们*不*在此事后重建 —— 后续 project
            # 变更由 session 的 ``set_project_root`` 处理。
            deps = production_deps(project_root=self.project_root)
            self.runner = Runner(deps=deps)

    # ------------------------------------------------------------------
    # 顶层入口（per-turn）
    # ------------------------------------------------------------------

    def run_turn(
        self,
        user_input: str,
    ) -> AsyncIterator[
        TextChunk | ActionEvent | Interrupt | ToolCall | ToolResult | Done | ErrorEvent
    ]:
        """便利方法：构造 :class:`RunnerContext` 并委派给 :meth:`Runner.run`。

        若上一轮产出了 :class:`Interrupt` 事件，则把待回答的 prompt
        与用户输入拼好后喂给 Runner（per :func:`compose_pending_input`）。
        """
        # 延迟 import 以避免循环 import（session.engine ↔ runner.runner）
        from writer.runner.context import RunnerContext

        composed_input = compose_pending_input(user_input, self.pending_interrupt)
        ctx = RunnerContext(
            user_input=composed_input,
            project_root=self.project_root,
            project_state=self.project_state,
            session_id=str(self.session_id),
        )
        assert self.runner is not None  # 由 __post_init__ 保障
        return self.runner.run(ctx)

    # ------------------------------------------------------------------
    # project_root + runner 重建
    # ------------------------------------------------------------------

    def set_project_root(self, new_root: Path | None) -> None:
        """更新 ``project_root`` 并重建 ``runner`` 内部的 deps。

        Router / tool_registry 在替换过程中保持不变。``tool_runtime``
        被重建，因为它持有用于 ``safe_path`` 检查的 project_root。

        在 ``chg-remove-roles`` 中移除：``_agent_for_genre`` +
        ``rebind_story_agent`` 块。``writer.roles.StoryAgent``（以及
        ``RunnerDeps.story_agent`` 字段）已删除，因此 session 不再需要在
        project / genre 变更时重建 Python-side 能力。LLM 派发的题材感知
        由 ``writer.agents.AgentRegistry`` 承载（见下文重建）。

        ``directive_registry`` 同样被重建（per ``chg-markdown-skills``），
        让新项目的 ``.writer/skills/`` 覆盖在下一 REPL 轮次可见。

        把 ``new_root`` 设为同一路径是 no-op（不重建）。
        把 ``new_root`` 设为 ``None`` 回退到 S0 哨兵根。

        实际替换通过 :meth:`RunnerDeps.rebind_*` 整体换 ``deps`` 后
        :meth:`Runner.replace_deps` 包装新 ``Runner`` 实现。
        """

        if new_root == self.project_root:
            return

        from writer.agents import built_agent_registry
        from writer.skills import built_directive_registry
        from writer.tools import ToolRuntime

        if new_root is not None:
            from writer.config import load_env_file, refresh_settings

            load_env_file(new_root)
            refresh_settings()

        self.project_root = new_root
        resolved = (new_root or _SENTINEL_PROJECT_ROOT).resolve()
        new_runtime = ToolRuntime(project_root=resolved)
        assert self.runner is not None
        new_deps = self.runner.deps.rebind_tool_runtime(new_runtime)
        self.refresh_project_state()
        self.refresh_project_genre()

        # 重建 directive registry，让新项目的 ``.writer/skills/``
        # 覆盖在下一轮次生效。``built_directive_registry`` 对 S0
        # 使用解析后的哨兵调用（而不是 ``None``），以便未来 S0 directive
        # stub 可以依赖真实路径；实际上哨兵不是目录，``discover_directives``
        # 返回 ``[]``。
        new_registry = built_directive_registry(project_root=resolved)
        new_deps = new_deps.rebind_directive_registry(new_registry)

        # 重建 agent registry，让新项目的 ``.writer/agents/``
        # 覆盖（per ``fea-agent-mirror``）在下一 REPL 轮次生效。
        # 与上方的 directive registry rebind 对称。
        new_agent_registry = built_agent_registry(project_root=resolved)
        new_deps = new_deps.rebind_agent_registry(new_agent_registry)

        # 重建 tool_loop(Bug 01):当原 deps 带 tool_loop 时,
        # 用新 runtime 重新构造,确保 ReActAgent._runtime 指向新根。
        # rule-only 部署(tool_loop=None)时保持 None。
        # 延迟 import 避免 runner.deps → llm.agent 循环。
        from writer.llm.agent import ReActAgent

        new_loop: ReActAgent | None = None
        if new_deps.tool_loop is not None:
            new_loop = ReActAgent(
                settings=new_deps.settings,
                registry=new_deps.tool_registry,
                runtime=new_runtime,
            )
        new_deps = new_deps.rebind_tool_loop(new_loop)

        # 整体替换 runner.deps；cfg / router / tool_registry 保持不变。
        self.runner = self.runner.replace_deps(new_deps)

    def refresh_project_state(self) -> str:
        """从磁盘文件刷新 ``project_state`` 并返回它。"""

        from writer.project import detect_state

        self.project_state = detect_state(self.project_root).value
        return self.project_state

    def refresh_project_genre(self) -> str:
        """从 ``(project_root / AGENT.md)`` 刷新 ``project_genre``。

        返回刷新后的值（缺失或为空时为 ``"other"``）。本方法不会抛异常
        —— 残缺的 AGENT.md 仅回退到 ``"other"``。由
        :meth:`set_project_root` 自动调用，也由希望在外部编辑
        ``AGENT.md`` 后重新读取的调用方按需调用。

        注（per ``chg-remove-roles``）：该值不再接入 Python-side
        ``StoryAgent`` 子类。``/状态`` 仍展示它；LLM 派发通过
        Markdown ``writer.agents.AgentRegistry`` 路由，后者从每个
        agent 的 ``AGENT.md`` frontmatter（或项目覆盖）读取题材。
        """

        if self.project_root is None:
            self.project_genre = "other"
        else:
            from writer.project import read_genre_from_agent

            self.project_genre = read_genre_from_agent(
                self.project_root / "AGENT.md"
            )
        return self.project_genre

    # ------------------------------------------------------------------
    # 轮次历史
    # ------------------------------------------------------------------

    def record_turn(self, user_input: str, done_reason: DoneReason) -> TurnRecord:
        """追加一条 :class:`TurnRecord` 并返回它。"""

        record = TurnRecord(
            turn_index=len(self.turns),
            user_input=user_input,
            done_reason=done_reason,
            timestamp=datetime.now(UTC),
        )
        self.turns.append(record)
        return record

    # ------------------------------------------------------------------
    # Pending Interrupt 生命周期
    # ------------------------------------------------------------------

    def set_pending_interrupt(self, interrupt: Interrupt) -> None:
        self.pending_interrupt = interrupt

    def clear_pending_interrupt(self) -> None:
        self.pending_interrupt = None


# ----------------------------------------------------------------------
# 模块级辅助函数
# ----------------------------------------------------------------------


def compose_pending_input(original: str, pending: Interrupt | None) -> str:
    """返回本轮喂给 Runner 的用户输入字符串。

    若 ``pending`` 已设置，则在 prompt 前添加可见标记，让 LLM 路由器
    同时看到上一个问题和用户的回答。当 ``pending`` 为 ``None`` 时，
    返回原输入。

    输出为纯文本 —— 标记用方括号包裹，以便在 REPL 日志和控制台
    打印中保持可见。
    """

    if pending is None:
        return original
    return f"[pending] {pending.prompt}\n[answer] {original}"


__all__ = [
    "Engine",
    "TurnRecord",
    "compose_pending_input",
]
