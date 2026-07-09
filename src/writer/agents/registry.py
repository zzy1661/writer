"""Agent registry —— 名称绑定 agent 的查找表。

Last-write-wins 语义：当相同的 ``name`` 跨层（shipped / project /
entry-point）出现多次时，后者替换前者。这种 Replace 语义让用户
可以通过添加同名 project agent 来覆盖任何内置 agent。

单层内的重复名称在 registry 构造时抛 :class:`AgentRegistryError`。
格式错乱的 agent 也会被前置拒绝（见 :func:`_validate`），让笔误
（``description = 123``）无法存活到首次 LLM 派发。

公开 API：

* :class:`AgentRegistry` —— 以 ``name`` 为键的查找表。
* :func:`built_agent_registry` —— 组装 shipped + project + entry-point
  层的工厂（name 冲突时后者覆盖前者）。
* :func:`builtin_agent_registry` —— 仅内置 agent。

:meth:`AgentRegistry.descriptions` 视图为父 LLM 的派发决策提供数据
（per :class:`writer.routing.LlmIntentRouter`）：

* 每个 description 被截断到 ≤ 200 字符。
* 总列表上限 16 个 agent（软警告而非错误），让 router 的 system prompt
  不会爆炸。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from writer.agents.protocol import Agent

log = logging.getLogger(__name__)


#: 第三方 agent 插件的 entry-point 组名。
ENTRY_POINT_GROUP = "writer.agents"


#: :meth:`AgentRegistry.descriptions` 中每个 description 的最大字符数。
DESCRIPTION_MAX_CHARS = 200

#: :meth:`AgentRegistry.descriptions` 返回的最大 agent 数。
DESCRIPTIONS_MAX_AGENTS = 16

#: 规范题材 key 的 allow-list（per ``fea-agent-mirror`` Decision 7）。
_VALID_GENRES: frozenset[str] = frozenset({"other", "历史", "言情", "玄幻"})

#: ``name`` 字段的模式 —— 小写字母开头，后跟字母 / 数字 / 下划线。
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class AgentRegistryError(ValueError):
    """agent 注册无效时抛出（错误名称、重复、schema 问题）。"""


def _validate(agent: object) -> None:
    """在注册时强制 agent 元数据契约。

    及早捕获问题，避免笔误（``description = 123``）一路存活到首次
    LLM 派发 —— 那里会以令人困惑的渲染异常暴露。
    """

    # 延迟 import 避免顶层循环（本模块由 writer.agents.__init__ import，
    # 后者在包初始化时可能在 protocol 完整解析前被加载）。
    from writer.agents.protocol import Agent

    if not isinstance(agent, Agent):
        msg = f"agent must be an Agent instance; got {type(agent).__name__}"
        raise AgentRegistryError(msg)

    if not isinstance(agent.name, str) or not _NAME_PATTERN.match(agent.name):
        msg = (
            f"Agent {agent!r} has invalid `name` {agent.name!r} "
            "(must match ^[a-z][a-z0-9_]*$)"
        )
        raise AgentRegistryError(msg)
    if not isinstance(agent.description, str) or not agent.description.strip():
        msg = f"Agent {agent.name!r} missing non-empty `description`"
        raise AgentRegistryError(msg)
    if not isinstance(agent.genre, str) or agent.genre not in _VALID_GENRES:
        msg = (
            f"Agent {agent.name!r} has invalid `genre` {agent.genre!r}; "
            f"expected one of {sorted(_VALID_GENRES)}"
        )
        raise AgentRegistryError(msg)
    if not isinstance(agent.body, str) or not agent.body.strip():
        msg = f"Agent {agent.name!r} missing non-empty `body`"
        raise AgentRegistryError(msg)


class AgentRegistry:
    """名称绑定 agent 的查找表。

    重复名称按 **last-write-wins** 语义解决：当相同的 ``name`` 跨层
    （shipped / project / entry-point）出现多次时，后者替换前者。
    这种 Replace 语义让用户可以通过添加同名 project agent 来覆盖
    任何内置 agent。

    逐 agent 校验会抛 :class:`AgentRegistryError`（通过 :func:`_validate`）——
    格式错乱的 agent 始终是硬错误，会中止 registry 构造。
    """

    def __init__(
        self,
        agents: list[Agent] | None = None,
        *,
        extra_agents: list[Agent] | None = None,
    ) -> None:
        items: list[Agent] = list(agents) if agents is not None else []
        if extra_agents:
            items.extend(extra_agents)

        seen: dict[str, Agent] = {}
        for agent in items:
            _validate(agent)
            seen[agent.name] = agent  # last-write-wins

        self._by_name: dict[str, Agent] = seen

    # ----- introspection --------------------------------------------------

    def get(self, name: str) -> Agent | None:
        return self._by_name.get(name)

    def require(self, name: str) -> Agent:
        """返回 ``name`` 对应的 agent，否则抛 :class:`AgentRegistryError`。

        镜像 :meth:`writer.skills.registry.DirectiveRegistry.run` 风格的
        严格性：缺失名称作为明确错误而非 ``None`` 暴露，让引擎的
        ``Done(aborted)`` payload 有信息量。
        """

        agent = self._by_name.get(name)
        if agent is None:
            available = sorted(self._by_name)
            msg = f"no agent registered for name {name!r}; available: {available}"
            raise AgentRegistryError(msg)
        return agent

    def all(self) -> list[Agent]:
        """返回所有已注册 agent，按名称排序。"""

        return [self._by_name[name] for name in sorted(self._by_name)]

    def names(self) -> list[str]:
        """返回排序后的 agent 名称（跨运行稳定）。"""

        return sorted(self._by_name)

    def descriptions(self) -> list[dict[str, str]]:
        """返回 ``[{name, description, genre}, …]`` 给 LLM 派发。

        每个 description 截断到 :data:`DESCRIPTION_MAX_CHARS`；总列表
        上限 :data:`DESCRIPTIONS_MAX_AGENTS`（截断时记 WARNING）。原始
        ``Agent`` 对象*不*被修改 —— 这是只读视图。
        """

        out: list[dict[str, str]] = []
        truncated_total = False
        for name in self.names():
            if len(out) >= DESCRIPTIONS_MAX_AGENTS:
                truncated_total = True
                break
            agent = self._by_name[name]
            description = agent.description
            if len(description) > DESCRIPTION_MAX_CHARS:
                description = description[:DESCRIPTION_MAX_CHARS]
            out.append(
                {
                    "name": name,
                    "description": description,
                    "genre": agent.genre,
                }
            )

        if truncated_total:
            log.warning(
                "AgentRegistry.descriptions() truncated from %d to %d "
                "agents to keep the LLM system prompt bounded",
                len(self._by_name),
                DESCRIPTIONS_MAX_AGENTS,
            )
        return out


__all__ = [
    "AgentRegistry",
    "AgentRegistryError",
    "DESCRIPTION_MAX_CHARS",
    "DESCRIPTIONS_MAX_AGENTS",
    "ENTRY_POINT_GROUP",
    "built_agent_registry",
    "builtin_agent_registry",
]


def builtin_agent_registry() -> AgentRegistry:
    """仅内置 agent —— 不含项目层、不含 entry-point 插件。

    被未绑定项目的调用方（测试、S0 路径）作为默认使用。
    """

    from writer.agents.agent_discovery import discover_shipped_agents  # noqa: PLC0415

    items: list[Agent] = list(discover_shipped_agents())  # type: ignore[arg-type]
    return AgentRegistry(agents=items)


def built_agent_registry(
    project_root: Path | None = None,
) -> AgentRegistry:
    """内置 agent + 项目级 agent + entry-point 插件。

    分层（Replace 语义 —— name 冲突时后者覆盖前者）：

    1. :func:`discover_shipped_agents` —— 4 个内置 agent。
    2. :func:`discover_agents(project_root)` —— 仅当提供
       ``project_root`` 时启用。
    3. :func:`discover_entry_point_agents` —— Python entry-point
       插件。

    ``project_root=None`` 路径保留既有行为（无项目层；为测试和未绑定
    项目的调用方保留兼容性）。本函数从不为缺失的项目文件抛异常
    （loader 把单文件错误吞为 warning），从不为缺失的 entry-point
    插件抛异常。真正的空 registry（无内置、无项目、无插件）依然合法。
    """

    from writer.agents.agent_discovery import (  # noqa: PLC0415
        discover_agents,
        discover_entry_point_agents,
        discover_shipped_agents,
    )

    items: list[Agent] = []
    items.extend(discover_shipped_agents())  # type: ignore[arg-type]
    if project_root is not None:
        items.extend(discover_agents(project_root))  # type: ignore[arg-type]
    items.extend(discover_entry_point_agents())  # type: ignore[arg-type]

    _check_builtin_sources_drift()

    if len(items) == 0:
        return AgentRegistry()
    return AgentRegistry(agents=items)


def _check_builtin_sources_drift() -> None:
    """当任何内置 agent 文件的 sha256 不再匹配时记录 WARNING。

    软检查 —— registry 仍会加载该文件（漂移是维护信号而非硬失败）。
    见 :class:`writer.agents.builtin_sources.BUILTIN_AGENT_SOURCES`。
    """

    try:
        from writer.agents.builtin_sources import BUILTIN_AGENT_SOURCES  # noqa: PLC0415
    except ImportError:
        return

    import hashlib
    import importlib.resources

    try:
        shipped_root = importlib.resources.files("writer.agents._shipped")
    except Exception:  # noqa: BLE001
        return

    for entry in BUILTIN_AGENT_SOURCES:
        try:
            traversable = shipped_root / entry.mirror_filename
            text = traversable.read_text(encoding="utf-8")
        except (OSError, NotImplementedError):
            continue
        actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual_sha != entry.source_sha256:
            log.warning(
                "Shipped agent %s drifted: expected sha=%s, actual sha=%s; "
                "registry will still load the drifted file but you may want "
                "to refresh BUILTIN_AGENT_SOURCES",
                entry.mirror_filename,
                entry.source_sha256,
                actual_sha,
            )
