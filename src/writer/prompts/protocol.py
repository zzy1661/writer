"""Prompt 协议 —— :mod:`writer.prompts.registry` 使用的元数据类型。

集中化 prompt 镜像 :mod:`writer.skills.registry` 和
:mod:`writer.tools.registry` 的设计选择：一个小巧的类型化包装加
一个可以在不动调用点的前提下替换或扩展的 registry。

:class:`PromptBundle` 是派发单元：它持有一个
:class:`langchain_core.prompts.ChatPromptTemplate` 加上注册时所用的
复合键（:class:`PromptKey`）。复合键形状为 ``(role, genre)``，
因为四个题材 Agent（``HistoryAgent`` / ``XuanhuanAgent`` /
``RomanceAgent` / ``StoryAgent``）都消费同一 ``outline`` 角色，
但身份不同。

dataclass 是 ``frozen=True``，让调用方在注册后无法修改 bundle —— 唯一
允许的替换 prompt 方式是构建新 registry。这与 :class:`writer.runner.events.Done`
（同样 ``frozen=True``）的既有约定一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate


@dataclass(frozen=True)
class PromptKey:
    """复合查找键 —— ``(role, genre)`` 覆盖大多数调用点。

    ``role`` 区分 LLM 调用的*种类*：
    ``"router"`` / ``"outline"`` / ``"toc"`` / ``"init_brief"``。

    ``genre`` 区分 agent 身份（以及题材特定的大纲回退）：
    ``"历史"`` / ``"言情"`` / ``"玄幻"`` / ``"other"``。默认
    ``"other"`` 是 :class:`writer.roles.StoryAgent` 使用的兜底，
    也用于 ``"toc"`` 和 ``"init_brief"`` 这类不分题材的共享角色。
    """

    role: str
    genre: str = "other"

    def __str__(self) -> str:
        if self.genre == "other":
            return self.role
        return f"{self.role}.{self.genre}"


@dataclass(frozen=True)
class PromptBundle:
    """一次 LLM 调用的完整表面。

    ``key`` 是查找句柄；``template`` 是调用点在调用 LLM 前渲染的内容；
    ``command`` 是可选提示，供希望把 prompt 映射回斜杠命令的工具使用
    （registry 查找逻辑不使用）。
    """

    key: PromptKey
    template: ChatPromptTemplate
    command: str | None = None


__all__ = ["PromptBundle", "PromptKey"]
