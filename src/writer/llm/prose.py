"""长篇散文 LLM 客户端。

现有 ``writer.llm`` 包覆盖两条路径：

* :mod:`writer.llm.structured` —— 短结构化输出调用（针对 JSON
  响应校验 Pydantic schema）。
* :mod:`writer.llm.agent` —— :class:`LLMToolLoop` ReAct 风格的工具调用。

两者都不适合**章节长度散文生成**：章节草稿是数千中文字符且无
schema，而 ``LLMToolLoop`` 针对与工具调用交错的短模型响应进行了
优化。本模块补齐缺失的第三条路径：

* :class:`LLMProseClient` —— 单方法
  ``generate_text(*, system, user) -> str`` 的 Protocol。
* :class:`RealProseClient` —— 包装 LangChain ``BaseChatModel``，
  以 system + human 消息对调用。
* :class:`DeterministicProseClient` —— 从项目上下文组装结构化散文
  （无 LLM 调用），让离线 / 无 API key 部署产出可用草稿。

:func:`writer.engine.deps.production_deps` 工厂在配置 API key 时
注入 Real 变体，否则注入 Deterministic 变体。该字段**始终**填充
（从不为 ``None``），与 ``tool_loop`` 不同 —— 后者在纯规则部署下
可以为 ``None``。

2026-07-09 增补（real-writing-pipeline PR2）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


class LLMProseError(ValueError):
    """:class:`LLMProseClient` 实现遇到传输 / 解析 / 协议失败时抛出。

    继承 :class:`ValueError`（与 :class:`LLMConfigError` 和
    :class:`StructuredOutputError` 一致），让引擎现有的
    ``except Exception`` 分支把它作为普通 aborted 轮次暴露。
    """


@runtime_checkable
class LLMProseClient(Protocol):
    """长篇散文生成契约。

    实现必须暴露 ``name`` 属性（字符串），让引擎和测试能在不导入
    具体类的情况下分支。实现还必须支持单个 keyword-only
    ``generate_text`` 方法，返回字符串。
    """

    name: str

    def generate_text(self, *, system: str, user: str) -> str:
        ...


def _coerce_ai_message_to_text(message: AIMessage) -> str:
    """把 LangChain ``AIMessage`` 的 content 字段强制为 ``str``。

    与 :func:`writer.llm.structured._message_content_to_text` 规则一致，
    让两条路径共享内容处理语义：

    * ``str`` → 原样返回
    * ``list`` 字符串 / dict → 用换行连接；带 ``text`` / ``content`` 键
      的 dict 项被字符串化
    * 其他类型 → ``str(content)`` 回退

    当内容为 ``None`` 或不支持的类型时抛 :class:`LLMProseError`。
    """
    content = message.content
    if content is None:
        raise LLMProseError("LLM 响应内容为 None")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(content, (int, float, bool)):
        return str(content)
    raise LLMProseError(f"LLM 响应内容类型不支持: {type(content).__name__}")


class RealProseClient:
    """LLM 支持的散文客户端。

    ``generate_text`` 调用 ``self.llm.invoke([SystemMessage, HumanMessage])``
    并把响应强制为 ``str``。为长篇章节草稿设计；调用方负责 token 预算
    （参见 :func:`writer.prompts.context.prep_context` 规范的上下文打包器）。
    """

    name: str = "real"

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm

    def generate_text(self, *, system: str, user: str) -> str:
        try:
            response = self._llm.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
        except Exception as exc:  # noqa: BLE001 — 暴露为领域异常
            raise LLMProseError(f"LLM 调用失败: {exc}") from exc
        if not isinstance(response, AIMessage):
            raise LLMProseError(
                f"LLM 返回了非 AIMessage: {type(response).__name__}"
            )
        return _coerce_ai_message_to_text(response)


@dataclass
class DeterministicProseClient:
    """离线散文客户端。

    从 prep_context 的 canon / history 块以及用户消息组装结构化散文
    （≥ 200 字符）—— 无 LLM 调用，无网络。针对测试、CI 和没有
    API key 的开发环境。

    输出遵循确定性的 3-beat 模板：

    * 章节标题行（``# 第 <id> 章 <task summary>``）
    * 开篇段（canon 摘要）
    * 冲突段（history 摘要）
    * 收尾钩子段

    ``prep_context_fn`` 默认 :func:`writer.prompts.context.prep_context`，
    但可以在测试中用 fake context pack 覆写。
    """

    name: str = "deterministic"
    prep_context_fn: Callable[..., Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.prep_context_fn is None:
            # 延迟 import：``writer.prompts.context`` 本身在 import 时不做重型
            # I/O，但 prose 模块在引擎栈中导入较早 —— 把 import 放在
            # ``__post_init__`` 内部，让用
            # ``DeterministicProseClient(prep_context_fn=fake)`` 构造
            # 的纯测试路径完全不触碰 ``writer.prompts.context``。
            from writer.prompts.context import prep_context

            self.prep_context_fn = prep_context

    def generate_text(self, *, system: str, user: str) -> str:
        # ``user`` 是每次调用的用户消息（携带工作流的 ``task:``）；
        # ``system`` 是 prep_context 的 system_block。
        # 用小而稳定的解析器从用户消息中抽取 chapter_id + task，
        # 让模板保持确定性。
        chapter_id, task_summary = _parse_user_message(user)

        # 用与 ``write_chapter._prep_context_node`` 相同的签名调用
        # prep_context，让输出看起来与 Real 模式草稿完全一致
        #（LLM 措辞除外）。
        pack = self.prep_context_fn(
            chapter_id,
            task_summary or user,
            project_root=None,
            max_tokens=8_000,
        )

        canon = _excerpt(pack.canon_block, limit=200)
        history = _excerpt(pack.history_block, limit=200)
        title = _chapter_title(chapter_id, task_summary)

        # 5 段模板：标题 + 开篇 + 冲突 + 正文 + 钩子。
        # 模板刻意用散文填充，让即使 prep_context 块为空或 task 是
        # 短词时，拼装出的文本也能稳定 ≥ 200 字符。Real 模式草稿
        # （LLM 输出）轻松越过这条线；确定性路径是测试断言的最坏
        # 情况。
        return (
            f"# {title}\n\n"
            f"本章承接正典设定，延续既有因果。{canon}\n\n"
            f"前情回顾：{history}\n\n"
            f"主角在矛盾中推进本章行动，保留前文伏笔；"
            f"围绕本章核心问题展开抉择与推进；"
            f"次要角色在关键时刻提供线索或阻力，丰富本章的层次；"
            f"环境与氛围描写服务于情节张力，强化情绪节奏；"
            f"对白与内心独白交替推进,呈现人物的立场与变化。\n\n"
            f"关键节点即将在下一章展开，章末留下新的期待与悬念，"
            f"为读者勾画下一章的方向。\n"
        )


def _parse_user_message(user: str) -> tuple[str, str]:
    """从工作流用户消息中提取 ``(chapter_id, task_summary)``。

    ``_plan_chapter_node`` 产出的用户消息格式是：

    .. code-block:: text

        chapter_id: <id>
        task: <task description>

    其他任何格式都回退到 ``("1.1", user)``，让 Deterministic
    客户端不会因意外输入而抛异常。
    """
    chapter_id = "1.1"
    task_summary = ""
    for line in user.splitlines():
        stripped = line.strip()
        if stripped.startswith("chapter_id:"):
            chapter_id = stripped.split(":", 1)[1].strip() or "1.1"
        elif stripped.startswith("task:"):
            task_summary = stripped.split(":", 1)[1].strip()
    if not task_summary:
        task_summary = user.strip()
    return chapter_id, task_summary


def _excerpt(text: str, *, limit: int = 120) -> str:
    """返回 ``text`` 前 ``limit`` 字符，折叠为单行。"""
    if not text:
        return "（暂无上下文）"
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _chapter_title(chapter_id: str, task_summary: str) -> str:
    """构造形如 ``第 1.1 章 <task>`` 的确定性章节标题。"""
    task = task_summary.strip() or "本章"
    # 限制 task 长度让标题保持合理。
    if len(task) > 24:
        task = task[:24] + "..."
    return f"第 {chapter_id} 章 {task}"


__all__ = [
    "DeterministicProseClient",
    "LLMProseClient",
    "LLMProseError",
    "RealProseClient",
]
