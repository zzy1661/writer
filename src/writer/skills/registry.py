"""Directive registry —— 命令绑定 directive 的查找表。

按 chg-markdown-skills Decision 3 从 ``SkillRegistry`` 更名而来。
内部 dict 的 value 类型从 ``Skill`` 改为 ``SkillDirective``；公开 API
（``get`` / ``commands`` / ``help_entries``）
形状与旧 registry 兼容，下游调用方（REPL 帮助 / Tab 补全）
不需要改动调用点 —— 只是类型名变了。

发现分三层（Replace 语义 —— 命令冲突时后者覆盖前者）：

1. :func:`writer.skills.directive_discovery.discover_shipped_directives`
   —— ``writer/skills/_shipped/`` 下的 4 个内置 directives。
2. :func:`writer.skills.directive_discovery.discover_directives` ——
   仅在提供 ``project_root`` 时启用。
3. :func:`discover_entry_point_directives` —— Python entry-point
   插件，位于 ``[project.entry-points."writer.directives"]``。

见 :func:`built_directive_registry` 的组装方式。
"""

from __future__ import annotations

import logging
from pathlib import Path

from writer.skills.directive_discovery import (
    discover_entry_point_directives,
    discover_shipped_directives,
)
from writer.skills.errors import SkillError
from writer.skills.protocol import SkillDirective

log = logging.getLogger(__name__)


#: 第三方 directive 插件的 entry-point 组名。
ENTRY_POINT_GROUP = "writer.directives"


def _validate(directive: SkillDirective) -> None:
    """在注册时强制 directive 元数据契约。

    及早捕获问题，避免把笔误（``description = 123``）一路放到首次
    ``/帮助`` 调用 —— 那里会以令人困惑的渲染异常暴露。
    """

    if not isinstance(directive.command, str) or not directive.command.startswith("/"):
        msg = (
            f"Directive {directive!r} has invalid `command` "
            "(must be a non-empty str starting with '/')"
        )
        raise SkillError(msg)
    if not isinstance(directive.description, str) or not directive.description.strip():
        msg = f"Directive {directive.command!r} missing non-empty `description`"
        raise SkillError(msg)


class DirectiveRegistry:
    """命令绑定 directive 的查找表。

    重复命令按 **last-write-wins** 语义解决：当相同的 ``command`` 跨层
    （shipped / project / entry-point）出现多次时，后者替换前者。
    这种 Replace 语义让用户可以通过添加同名 project directive
    来覆盖任何 shipped directive。

    逐 directive 校验仍会抛 :class:`SkillError`（通过 :func:`_validate`）——
    格式错乱的 directive 始终是硬错误，会中止 registry 构造。
    """

    def __init__(
        self,
        directives: list[SkillDirective] | None = None,
        *,
        extra_directives: list[SkillDirective] | None = None,
    ) -> None:
        items: list[SkillDirective] = (
            list(directives) if directives is not None else []
        )
        if extra_directives:
            items.extend(extra_directives)

        seen: dict[str, SkillDirective] = {}
        for directive in items:
            _validate(directive)
            seen[directive.command] = directive

        self._by_command: dict[str, SkillDirective] = seen

    # ----- introspection ----------------------------------------------------

    def get(self, command: str) -> SkillDirective | None:
        return self._by_command.get(command)

    def commands(self) -> list[str]:
        """返回排序后的斜杠命令（跨运行稳定）。"""

        return sorted(self._by_command)

    def help_entries(self) -> list[tuple[str, str]]:
        """按 registry 顺序返回 ``[(command, description), …]``。

        按 :meth:`commands` 排序，让 ``/帮助`` 渲染不受插入顺序
        影响。
        """

        return [(cmd, self._by_command[cmd].description) for cmd in self.commands()]

    # ----- execution --------------------------------------------------------

    def get_body_with_references(
        self, command: str
    ) -> tuple[str, list[tuple[str, str]]] | None:
        """返回 ``command`` 的 ``(body, resolved_references)``。

        ``resolved_references`` 是 body 中 ``@reference path`` 提及
        所匹配的 ``(relpath, content)`` 对列表，按出现顺序。若命令
        未注册则返回 ``None``。

        延迟 import 以避免模块加载时 registry 与 directive_discovery
        之间的循环 import。
        """

        directive = self.get(command)
        if directive is None:
            return None
        # 本地 import：directive_discovery 从本模块层 import，
        # 所以我们在调用时再解析引用，避免循环。
        from writer.skills.directive_discovery import resolve_references  # noqa: PLC0415

        return directive.body, resolve_references(directive.body, directive.references)


__all__ = [
    "DirectiveRegistry",
    "ENTRY_POINT_GROUP",
    "built_directive_registry",
]


def built_directive_registry(
    project_root: Path | None = None,
) -> DirectiveRegistry:
    """内置 directives + 项目级 directives + entry-point directives。

    分层（Replace 语义 —— 命令冲突时后者覆盖前者）：

    1. :func:`discover_shipped_directives` —— 4 个内置 directives。
    2. :func:`discover_directives(project_root)` —— 仅当提供
       ``project_root`` 时启用。
    3. :func:`discover_entry_point_directives` —— Python entry-point
       插件。

    ``project_root=None`` 路径保留既有行为（无项目层；为测试和未绑定
    项目的调用方保留兼容性）。

    本函数从不为缺失的项目 skills 抛异常（loader 把单文件错误吞为
    warning），从不为缺失的 entry-point 插件抛异常。真正的空 registry
    （无内置、无项目、无插件）依然合法。
    """

    items: list[SkillDirective] = list(discover_shipped_directives())

    if project_root is not None:
        from writer.skills.directive_discovery import discover_directives  # noqa: PLC0415

        items.extend(discover_directives(project_root))

    items.extend(discover_entry_point_directives())

    if len(items) == 0:
        # 无内置 AND 无项目 AND 无插件。生产中不应发生（shipped 层
        # 总会提供 4 个），但我们为测试 + bootstrap 容忍这种情况。
        return DirectiveRegistry()
    return DirectiveRegistry(directives=items)
