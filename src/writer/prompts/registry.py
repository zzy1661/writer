"""Prompt registry —— 把 :class:`PromptKey` 映射到 :class:`PromptBundle`。

本模块镜像 :mod:`writer.skills.registry.SkillRegistry` 和
:mod:`writer.tools.registry.built_tool_registry` 的设计：

* :class:`PromptRegistry` 是以 :class:`PromptKey` 为键的薄查找表。
  内置 prompts 通过 ``prompts=`` 传入；第三方插件通过
  :func:`discover_entry_point_prompts` 加载并通过 ``extra_prompts=``
  合并。内置在 key 冲突时胜出 —— 影子覆盖核心 prompt 的插件触发
  duplicate-key 错误而非悄悄覆盖。
* :func:`builtin_prompt_registry` 仅返回内置 prompts。
  ``JSON_CONTRACT_TEMPLATE`` 风格的 deepseek 回退*不*在此注册，因为
  它依赖调用时提供的运行时 Pydantic schema；调用方应在调用时通过
  :func:`writer.prompts.shared.json_contract_message` 组装。
* :func:`discover_entry_point_prompts` 读取
  ``[project.entry-points."writer.prompts"]``，让第三方插件无需
  fork registry 即可提供额外 prompts。

:exc:`PromptRegistryError` 异常类型与 :exc:`writer.skills.errors.SkillError`
并行，让两个 registry 在配置错误时都大声失败。
"""

from __future__ import annotations

import logging
from importlib import metadata
from typing import TYPE_CHECKING

from writer.prompts.agents import (
    INIT_BRIEF_TEMPLATE,
    OUTLINE_TEMPLATE_HISTORY,
    OUTLINE_TEMPLATE_ROMANCE,
    OUTLINE_TEMPLATE_STORY,
    OUTLINE_TEMPLATE_XUANHUAN,
    TOC_TEMPLATE,
)
from writer.prompts.protocol import PromptBundle, PromptKey
from writer.prompts.router import COMMAND_AGENT_TEMPLATE

if TYPE_CHECKING:
    from pydantic import BaseModel

log = logging.getLogger(__name__)


ENTRY_POINT_GROUP = "writer.prompts"


class PromptRegistryError(ValueError):
    """prompt 注册无效时抛出（错误键、重复）。"""


# 与 agent 一起内置的 prompts。顺序仅对 :class:`PromptRegistry` 中
# fall-through 默认参数情形有意义 —— 后注册者按键冲突胜出，镜像
# skills registry 行为。内置在 :func:`built_prompt_registry` 中优先
# 列出，让影子覆盖核心键的插件触发 duplicate-key 错误。
BUILTIN_PROMPTS: list[PromptBundle] = [
    PromptBundle(
        key=PromptKey(role="router"),
        template=COMMAND_AGENT_TEMPLATE,
        command=None,
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="other"),
        template=OUTLINE_TEMPLATE_STORY,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="历史"),
        template=OUTLINE_TEMPLATE_HISTORY,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="言情"),
        template=OUTLINE_TEMPLATE_ROMANCE,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="玄幻"),
        template=OUTLINE_TEMPLATE_XUANHUAN,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="toc"),
        template=TOC_TEMPLATE,
        command="/目录",
    ),
    PromptBundle(
        key=PromptKey(role="init_brief"),
        template=INIT_BRIEF_TEMPLATE,
        command="/init",
    ),
]


class PromptRegistry:
    """:class:`PromptBundle` 的查找表。

    重复键在构造时抛 :class:`PromptRegistryError`。先注册者优先
    （通过 :func:`built_prompt_registry`，内置在 entry points 之前加入）。
    """

    def __init__(
        self,
        prompts: list[PromptBundle] | None = None,
        *,
        extra_prompts: list[PromptBundle] | None = None,
    ) -> None:
        items: list[PromptBundle] = list(prompts) if prompts is not None else list(BUILTIN_PROMPTS)
        if extra_prompts:
            items.extend(extra_prompts)

        seen: dict[PromptKey, PromptBundle] = {}
        for bundle in items:
            self._validate_bundle(bundle)
            if bundle.key in seen:
                msg = (
                    f"duplicate prompt key {bundle.key!s}: "
                    f"{seen[bundle.key].template!r} vs {bundle.template!r}"
                )
                raise PromptRegistryError(msg)
            seen[bundle.key] = bundle

        self._by_key: dict[PromptKey, PromptBundle] = seen

    # ----- introspection ----------------------------------------------------

    def get(self, key: PromptKey) -> PromptBundle | None:
        return self._by_key.get(key)

    def require(self, key: PromptKey) -> PromptBundle:
        """返回 ``key`` 对应的 bundle，否则抛 :class:`PromptRegistryError`。

        镜像 :meth:`writer.skills.registry.SkillRegistry.run` 的风格：
        缺失键作为明确错误而非 ``None`` 暴露。
        """

        bundle = self._by_key.get(key)
        if bundle is None:
            msg = f"no prompt registered for key {key!s}"
            raise PromptRegistryError(msg)
        return bundle

    def by_role(self, role: str) -> list[PromptBundle]:
        """返回所有键 ``role=role`` 的 bundle，按 genre 排序。"""

        return sorted(
            (bundle for bundle in self._by_key.values() if bundle.key.role == role),
            key=lambda bundle: bundle.key.genre,
        )

    def by_schema(self, schema: type[BaseModel]) -> list[PromptBundle]:
        """返回所有在其模板变量中声明 ``schema`` 的 bundle。

        这是给工具使用的*提示*表面 —— 把 Pydantic 模型映射回生成它的
        prompts（例如文档或测试中的静态健全性检查）。它遍历模板声明的
        输入变量并按名称相等匹配。
        """

        target_name = schema.__name__
        return [
            bundle
            for bundle in self._by_key.values()
            if any(
                var_name == target_name
                for var_name in (
                    bundle.template.input_variables
                    if hasattr(bundle.template, "input_variables")
                    else ()
                )
            )
        ]

    def keys(self) -> list[PromptKey]:
        """返回所有已注册键，按字符串形式排序。"""

        return sorted(self._by_key, key=str)

    # ----- validation -------------------------------------------------------

    @staticmethod
    def _validate_bundle(bundle: PromptBundle) -> None:
        if not isinstance(bundle.key, PromptKey):
            msg = f"bundle key must be PromptKey, got {type(bundle.key).__name__}"
            raise PromptRegistryError(msg)
        if not bundle.key.role:
            msg = "bundle key.role must be a non-empty string"
            raise PromptRegistryError(msg)
        if not bundle.key.genre:
            msg = "bundle key.genre must be a non-empty string"
            raise PromptRegistryError(msg)
        if bundle.template is None:  # pragma: no cover — defensive
            msg = f"bundle {bundle.key!s} has no template"
            raise PromptRegistryError(msg)


def discover_entry_point_prompts() -> list[PromptBundle]:
    """发现以 ``[project.entry-points."writer.prompts"]`` 注册的 prompts。

    每个 entry point 可解析为：

    * :class:`PromptBundle` 类 —— 以无参方式实例化；
    * 预先构造好的 :class:`PromptBundle` 实例 —— 直接使用。

    任何解析失败（distribution 缺失、ImportError、属性错误、意外类型、
    校验器抛 :exc:`PromptRegistryError`）都以 WARNING 记录并跳过 ——
    损坏的插件永不阻塞启动。
    """

    discovered: list[PromptBundle] = []
    try:
        entries = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # noqa: BLE001 — entry-points API 在奇怪环境中可能抛
        log.warning("Prompt entry_points discovery failed; continuing without plugins")
        return discovered

    for entry in entries:
        try:
            target = entry.load()
        except Exception:  # noqa: BLE001 — 行为不当的插件不得让启动崩溃
            log.warning(
                "Failed to import prompt entry point %s=%s; skipping",
                entry.name,
                entry.value,
            )
            continue

        try:
            if isinstance(target, type):
                instance: PromptBundle = target()  # type: ignore[abstract]
            elif isinstance(target, PromptBundle):
                instance = target
            else:
                log.warning(
                    "Prompt entry point %s did not resolve to a PromptBundle "
                    "(got %s); skipping",
                    entry.name,
                    type(target).__name__,
                )
                continue
        except Exception:  # noqa: BLE001 — 构造函数失败不得让启动崩溃
            log.warning(
                "Prompt entry point %s constructor raised; skipping",
                entry.name,
            )
            continue

        try:
            PromptRegistry._validate_bundle(instance)
        except PromptRegistryError as exc:
            log.warning("Prompt entry point %s rejected: %s", entry.name, exc)
            continue

        discovered.append(instance)
    return discovered


def builtin_prompt_registry() -> PromptRegistry:
    """仅内置 prompts —— 不含 entry-point 插件。

    作为 :class:`writer.roles.StoryAgent` 的默认（当调用方未注入自定义
    registry 时）。需要干净 registry 的测试（不含插件）应调用本函数
    而非 :func:`built_prompt_registry`。
    """

    return PromptRegistry()


def built_prompt_registry() -> PromptRegistry:
    """内置 prompts + entry-point 插件；内置在键冲突时胜出。

    镜像 :func:`writer.skills.registry.built_skill_registry`。内置
    优先列出，让影子覆盖 ``outline.历史`` 的插件触发
    :class:`PromptRegistry.__init__` 中的 duplicate-key 错误 ——
    静默允许插件清空核心 prompt 会让行为不确定且难以调试。
    """

    extras = discover_entry_point_prompts()
    if not extras:
        return PromptRegistry()
    return PromptRegistry(prompts=list(BUILTIN_PROMPTS), extra_prompts=extras)


__all__ = [
    "BUILTIN_PROMPTS",
    "ENTRY_POINT_GROUP",
    "PromptRegistry",
    "PromptRegistryError",
    "built_prompt_registry",
    "builtin_prompt_registry",
    "discover_entry_point_prompts",
]
