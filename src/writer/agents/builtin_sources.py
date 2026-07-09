"""内置 agent 源 —— 漂移检测元数据。

每条记录了内置 ``.md`` 文件的预期 ``sha256``，以便
:func:`writer.agents.registry._check_builtin_sources_drift` 在
registry 构造时若文件在记录哈希后被修改则发出警告。这是软检查
（registry 仍会加载该文件），但作为维护信号很有用。

编辑内置文件后刷新哈希：

1. 计算 ``sha256 src/writer/agents/_shipped/<name>.md``
2. 更新匹配条目的 ``source_sha256`` 字段
3. 运行 ``uv run pytest tests/test_agent_registry.py -k drift``
   确认警告消失
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinAgentSource:
    """一个内置 agent 的身份 + 完整性元数据。

    字段：

    * ``mirror_filename`` —— 文件名，位于
      ``src/writer/agents/_shipped/`` 下（例如 ``历史.md``）。
    * ``source_module`` —— ``importlib.resources`` 使用的点分模块路径
      （``writer.agents._shipped``）。
    * ``source_sha256`` —— 文件 UTF-8 内容的预期 sha256；registry
      在不匹配时记 WARNING。
    """

    mirror_filename: str
    source_module: str
    source_sha256: str


#: 位于 ``writer.agents._shipped/`` 的内置 agent。顺序仅供展示；发现
#: 按文件名排序。sha256 值由 .md 文件的 apply 阶段写入填充
#: （见 ``fea-agent-mirror/tasks.md`` 的 tasks 2.5 / 2.6）。
#: 在此之前每条都用占位符；漂移检测会在首次 registry 构造时响亮
#: 触发，那就是 apply 阶段刷新它们的触发点。
BUILTIN_AGENT_SOURCES: tuple[BuiltinAgentSource, ...] = (
    BuiltinAgentSource(
        mirror_filename="other.md",
        source_module="writer.agents._shipped",
        source_sha256="3a0060e21ff31c9db0a1395f7ed98767ebd6c1027fa3c01b0f6e5e976735c625",
    ),
    BuiltinAgentSource(
        mirror_filename="历史.md",
        source_module="writer.agents._shipped",
        source_sha256="b602b870cf1513809d2f1ed8c238e09c38ba0b2295338ce404079440e99beafd",
    ),
    BuiltinAgentSource(
        mirror_filename="言情.md",
        source_module="writer.agents._shipped",
        source_sha256="388b81262e6566b54b0d821bc7aec7f4d7c8f429c831dc97430797a5d6e55326",
    ),
    BuiltinAgentSource(
        mirror_filename="玄幻.md",
        source_module="writer.agents._shipped",
        source_sha256="23f448f5b62f80a9d70c59e20b2555054bb9e206c6930022a1e5f83e8ecfd08d",
    ),
)


__all__ = ["BUILTIN_AGENT_SOURCES", "BuiltinAgentSource"]
