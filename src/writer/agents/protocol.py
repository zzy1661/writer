"""Agent Protocol —— 纯 Markdown frontmatter 范式。

agent 是一组自包含的指令集，存储为单个 ``.md`` 文件（镜像 Claude
Code 的 ``~/.claude/agents/`` 布局）。每个 agent 拥有：

* ``name`` —— 稳定标识符（``history`` / ``romance`` / ``xuanhuan``
  / ``other``）。被 :class:`AgentRegistry` 用作 dict 键，被父 LLM
  用于在 :class:`AgentAction` 中设置 ``target_agent=``。
* ``description`` —— 父 LLM 读取的自然语言一行说明，用来决定是否
  派发给本 agent。要求信息丰富：应列出 3 个或更多具体触发场景。
* ``genre`` —— 规范的项目题材 key（``other`` / ``历史`` /
  ``言情`` / ``玄幻``）。被 LLM 调用层用来查找对应大纲 / TOC /
  init-brief 流的 :class:`ChatPromptTemplate`；**不**用于派发
  （LLM 基于 ``description`` 选择）。
* ``body`` —— ``.md`` 文件的完整 Markdown body（frontmatter 去掉，
  末尾空白规范化）。成为 agent LLM 调用的 system identity。
* ``tools_allowlist`` —— 本 agent 允许调用的工具名可选 tuple。
  **为未来保留**；引擎暂不强制该列表（per ``fea-agent-mirror``
  设计决策：先暴露该字段，强制延后到后续 change）。
* ``root`` —— agent 文件的绝对路径，用于诊断和未来 safe-path 集成。

发现通过 :func:`writer.agents.agent_discovery.discover_agents`
（项目级）和 :func:`...discover_shipped_agents`（包内置，
位于 ``writer/agents/_shipped/``）完成。两者的产物都汇入
:class:`writer.agents.registry.AgentRegistry`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Agent:
    """加载后的 ``<name>.md`` agent。

    字段契约见模块 docstring。
    """

    name: str
    description: str
    genre: str
    body: str
    tools_allowlist: tuple[str, ...] = ()
    root: Path = field(default_factory=Path)


__all__ = ["Agent"]
