"""Agent 系统 —— Claude Code ``.claude/agents/`` 镜像。

每个 agent 是一个带 YAML frontmatter（``name`` / ``description`` /
``genre``）的 ``.md`` 文件，加上一个 Markdown body 作为该 agent
在 LLM 调用时的 system prompt。父 LLM 读取每个 agent 的 ``description``
来决定是否派发给它（通过 ``AgentAction.target_agent``）。

公开 API（per ``fea-agent-mirror``）：

* :class:`Agent` —— 从 ``<name>.md`` 加载的冻结 dataclass。
* :class:`AgentRegistry` —— 以 ``name`` 为键的查找表（last-write-wins）。
* :func:`built_agent_registry` —— 组装 shipped + project + entry-point
  层的工厂（name 冲突时后者覆盖前者）。
* :func:`builtin_agent_registry` —— 仅内置 agent。
* :func:`discover_agents` —— 扫描项目的 ``.writer/agents/`` 目录。
* :func:`discover_shipped_agents` —— 列出 4 个内置 agent。
* :func:`discover_entry_point_agents` —— entry-point 插件钩子。
* :class:`AgentRegistryError` —— 领域异常。
* :func:`parse_agent_file` —— 解析一个 ``.md`` 文件（测试使用）。

能力层（per ``chg-remove-roles``）：

* :class:`InitBriefResult` —— post-init 梗概的结构化输出。
* :func:`process_init_brief` —— ``roles`` 包删除后唯一保留的 Python-side
  helper。被引擎的 ``_run_init_brief_command`` 与 CLI 的
  ``_maybe_apply_init_brief`` 路径共同使用。
"""

from writer.agents.agent_discovery import (
    discover_agents,
    discover_entry_point_agents,
    discover_shipped_agents,
    parse_agent_file,
)
from writer.agents.capability import InitBriefResult, process_init_brief
from writer.agents.protocol import Agent
from writer.agents.registry import (
    AgentRegistry,
    AgentRegistryError,
    built_agent_registry,
    builtin_agent_registry,
)

__all__ = [
    "Agent",
    "AgentRegistry",
    "AgentRegistryError",
    "InitBriefResult",
    "built_agent_registry",
    "builtin_agent_registry",
    "discover_agents",
    "discover_entry_point_agents",
    "discover_shipped_agents",
    "parse_agent_file",
    "process_init_brief",
]
