"""Agent 能力 —— LLM 不直接执行的 Python-side 辅助函数。

Markdown 范式的 agent 系统（``writer.agents.AgentRegistry`` /
``writer.agents.Agent``）承载 *身份*（agent 用于 LLM 派发的 system prompt）。
它*不*承载 *能力*（在 LLM 调用前后运行的确定性 Python 辅助函数、文件
写入、结构化输出解析等）。本模块把那些 Python-side 辅助函数集中起来，
让 "Agent" 概念有单一的语义归属 —— Markdown 身份层和确定性 Python
能力层都位于 :mod:`writer.agents`。

原能力表面（``StoryAgent`` / ``HistoryAgent` / ``XuanhuanAgent` /
``RomanceAgent``）在 ``chg-remove-roles`` 清理中删除，因为
``fea-agent-mirror`` 把面向 LLM 的身份迁移到 Markdown 之后，除
:func:`process_init_brief` 之外的所有方法都成了死代码。剩下的辅助
函数被暴露为自由函数而非类，因为：

* 它没有状态化资源 —— ``Settings`` 和 ``BaseChatModel`` 作为调用参数
  传入。
* 它不分 ``genre``（prompt 模板和 schema 与题材无关；每个题材的专门
  化由 Markdown agent 处理）。
* 类形态的 ``ReActAgent`` 仅因它循环并持有状态而存活；本函数两者
  都不需要。

公开 API（per ``chg-remove-roles``）：

* :class:`InitBriefResult` —— post-init 梗概的冻结 dataclass。
* :func:`process_init_brief` —— ``roles`` 包删除后唯一保留的 Python-side
  辅助函数。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from writer.config import Settings

log = logging.getLogger(__name__)


class _InitBriefPayload(BaseModel):
    """``process_init_brief`` LLM 结构化输出的 Pydantic schema。"""

    core_idea: str = Field(min_length=1)
    requirements: str = Field(min_length=1)


@dataclass(frozen=True)
class InitBriefResult:
    """post-init 创意梗概的结构化输出。

    字段：
        core_idea: ``创意/核心创意.md`` 的 Markdown body（字符串）。
        requirements: 追加到 ``AGENT.md`` 的 ``## 基本要求`` 段的
            Markdown 列表。
        source: 结构化输出路径成功时为 ``"llm"``；LLM 不可用 /
            失败时为 ``"fallback"``。
    """

    core_idea: str
    requirements: str
    source: str = "fallback"


def _process_init_brief_fallback(brief: str) -> InitBriefResult:
    """离线模式 init 梗概 —— 未配置 API key 时使用。"""

    return InitBriefResult(
        core_idea=(
            f"# 核心创意\n\n"
            f"{brief}\n\n"
            "## 扩写\n\n"
            "（离线模式：请配置 WRITER_API_KEY 后重新运行 init 以获得 LLM 扩写。）\n"
        ),
        requirements=(
            f"- 用户原始描述: {brief}\n"
            "- 篇幅目标: 20–50 万字长篇\n"
            "- 风格: 中文网文\n"
        ),
        source="fallback",
    )


def _process_init_brief_with_llm(
    brief: str,
    settings: Settings,
    llm: BaseChatModel,
) -> InitBriefResult:
    """LLM 支持的 init 梗概 —— 使用集中式 prompt registry。

    延迟 import 让 :mod:`writer.llm` 和 :mod:`writer.prompts` 不在引擎
    import 时拖入整个栈（纯规则部署永不需这两者）。
    """

    from writer.llm import get_llm, invoke_structured_json
    from writer.prompts import PromptKey, builtin_prompt_registry

    llm = llm or get_llm(settings)
    registry = builtin_prompt_registry()
    bundle = registry.require(PromptKey(role="init_brief"))
    messages = bundle.template.format_messages(brief=brief)
    payload = invoke_structured_json(llm, messages, _InitBriefPayload)

    core = payload.core_idea.strip()
    reqs = payload.requirements.strip()
    if not core.startswith("#"):
        core = f"# 核心创意\n\n{core}"
    return InitBriefResult(core_idea=core + "\n", requirements=reqs, source="llm")


def process_init_brief(
    brief: str,
    *,
    settings: Settings,
    llm: BaseChatModel | None = None,
) -> InitBriefResult:
    """把自然语言梗概展开为项目的 ``InitBriefResult``。

    行为：

    * 空 / 纯空白 ``brief`` → ``ValueError``。
    * 已配置 API key（或注入 ``llm=``）→ 用 ``init_brief`` prompt
      模板调用 LLM；任何 LLM-side 失败回退到确定性 Markdown
      （以 WARNING 记录）。
    * 无 API key → 确定性 Markdown。

    本辅助函数是 ``chg-remove-roles`` 清理后**唯一**幸存的 Python-side
    能力。``outline`` / ``toc`` 起草不再是 Python 辅助函数 —— 由 LLM
    消费 ``writer/agents/_shipped/*.md`` 身份来执行（指令见
    ``writer/skills/_shipped/大纲/SKILL.md``）。
    """

    normalized = brief.strip()
    if not normalized:
        msg = "创意描述不能为空。"
        raise ValueError(msg)

    if settings.has_api_key or llm is not None:
        try:
            return _process_init_brief_with_llm(normalized, settings, llm)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — role 必须优雅降级
            log.warning(
                "LLM init brief 失败，回退到本地摘要: %r", exc, exc_info=True
            )
    return _process_init_brief_fallback(normalized)


__all__ = ["InitBriefResult", "process_init_brief"]
