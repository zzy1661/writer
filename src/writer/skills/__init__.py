"""Directive 系统 —— 纯 Markdown SKILL.md 范式。

每个 directive 是 ``<project_root>/.writer/skills/``（或内置位于
``src/writer/skills/_shipped/``）下的一个目录，包含 ``SKILL.md``
以及可选的 ``references/`` 和 ``scripts/`` 子目录。通过
``directive_discovery`` 辅助函数发现；引擎把 directive 的 body
和 ``@reference`` 引用的文件读进 LLM 上下文。

公开 API（per chg-markdown-skills）：

* :class:`SkillDirective` —— 从 ``SKILL.md`` 加载的冻结 dataclass。
* :class:`DirectiveRegistry` —— 以 ``command`` 为键的查找表。
* :func:`built_directive_registry` —— 组装 shipped + project + entry-point
  层的工厂（命令冲突时后者覆盖前者）。
* :func:`discover_directives` —— 扫描项目的 skills 目录。
* :func:`discover_shipped_directives` —— 列出 4 个内置 directives。
* :func:`discover_entry_point_directives` —— entry-point 插件钩子。
* :class:`SkillError` —— 领域异常（re-export 以兼容）。
"""

from writer.skills.directive_discovery import (
    discover_directives,
    discover_shipped_directives,
    resolve_references,
)
from writer.skills.errors import SkillError
from writer.skills.protocol import SkillDirective
from writer.skills.registry import (
    ENTRY_POINT_GROUP,
    DirectiveRegistry,
    built_directive_registry,
    discover_entry_point_directives,
)

__all__ = [
    "DirectiveRegistry",
    "ENTRY_POINT_GROUP",
    "SkillDirective",
    "SkillError",
    "built_directive_registry",
    "discover_directives",
    "discover_entry_point_directives",
    "discover_shipped_directives",
    "resolve_references",
]
