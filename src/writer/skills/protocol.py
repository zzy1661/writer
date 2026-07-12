"""Directive Protocol —— 纯 Markdown SKILL.md 范式。

directive 是一组自包含的指令集，存储于 ``<command>/SKILL.md``
（镜像 Claude Code 的 ``~/.claude/skills/`` 布局）。引擎把 directive
的 body 和 ``@reference`` 引用读入 LLM 上下文，LLM 通过既有 tool
registry 完成实际工作 —— 没有 Python ``run()`` 方法。

通过 :func:`writer.skills.directive_discovery.discover_directives`
（项目级）和 :func:`...discover_shipped_directives`（包内置，
位于 ``writer/skills/_shipped/``）发现。两者的产物都汇入
:class:`writer.skills.registry.DirectiveRegistry`。

元数据契约（``command`` / ``description`` / ``body`` /
``references`` / ``scripts`` / ``root``）驱动 3 个
下游表面：

* ``/帮助`` —— :func:`writer.cli.main.print_repl_help` 使用
  :meth:`writer.skills.registry.DirectiveRegistry.help_entries`
  渲染命令表，无需触及 SKILL.md 解析。
* REPL 补全 —— :func:`writer.cli.main.build_prompt_session` 使用
  :meth:`DirectiveRegistry.commands` 做 Tab 补全。
* Engine dispatch —— :func:`writer.engine.loop.run_engine` 识别
  匹配的 ``command``，把 directive 的 body + references 通过既有
  工具循环喂给 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SkillDirective:
    """加载后的 ``<command>/SKILL.md`` directive。

    字段：

    * ``command`` —— 斜杠命令（来自 YAML frontmatter）。
    * ``description`` —— 人类可读的一行说明（来自 YAML frontmatter）。
    * ``body`` —— ``SKILL.md`` 的完整 Markdown body（去掉 frontmatter，
      末尾空白被规范化）。
    * ``references`` —— ``<command>/references/`` 下每个 ``*.md``
      的 ``{relpath: content}``。目录不存在时为 ``{}``。
    * ``scripts`` —— ``<command>/scripts/`` 下文件的相对路径列表。
      目录不存在时为 ``[]``。
    * ``root`` —— directive 所在目录的绝对路径，让引擎能通过
      ``safe_path`` 解析脚本执行路径。
    """

    command: str
    description: str
    body: str
    references: dict[str, str] = field(default_factory=dict)
    scripts: list[str] = field(default_factory=list)
    root: Path = field(default_factory=Path)


__all__ = ["SkillDirective"]
