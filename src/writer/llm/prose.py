"""Long-form prose LLM client.

The existing ``writer.llm`` package covers two paths:

* :mod:`writer.llm.structured` — short structured-output calls (Pydantic
  schema validated against a JSON response).
* :mod:`writer.llm.agent` — :class:`LLMToolLoop` ReAct-style tool calls.

Neither is a good fit for **chapter-length prose generation**: a chapter
draft is several thousand Chinese characters with no schema, and the
``LLMToolLoop`` is optimised for short model responses interleaved with
tool calls. This module adds the missing third path:

* :class:`LLMProseClient` — Protocol with a single
  ``generate_text(*, system, user) -> str`` method.
* :class:`RealProseClient` — wraps a LangChain ``BaseChatModel`` and
  invokes it with a system + human message pair.
* :class:`DeterministicProseClient` — assembles structured prose from
  the project context (no LLM call) so offline / no-API-key deployments
  produce a usable draft.

The :func:`writer.engine.deps.production_deps` factory injects the
Real variant when an API key is configured, otherwise the Deterministic
variant. The field is **always** populated (never ``None``), unlike
``tool_loop`` which can be ``None`` for rule-only deployments.

Added 2026-07-09 (real-writing-pipeline PR2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


class LLMProseError(ValueError):
    """Raised by :class:`LLMProseClient` implementations on transport /
    parse / protocol failures.

    Inherits from :class:`ValueError` (same as :class:`LLMConfigError` and
    :class:`StructuredOutputError`) so the engine's existing
    ``except Exception`` arm surfaces it as a normal aborted turn.
    """


@runtime_checkable
class LLMProseClient(Protocol):
    """Long-form prose generation contract.

    Implementations MUST expose a ``name`` attribute (string) so the
    engine and tests can branch on the implementation without importing
    the concrete class. Implementations MUST also support a single
    keyword-only ``generate_text`` method that returns a string.
    """

    name: str

    def generate_text(self, *, system: str, user: str) -> str:
        ...


def _coerce_ai_message_to_text(message: AIMessage) -> str:
    """Coerce a LangChain ``AIMessage`` content field to ``str``.

    Mirrors the rules in :func:`writer.llm.structured._message_content_to_text`
    so the two paths share content-handling semantics:

    * ``str`` → returned as-is
    * ``list`` of strings / dicts → joined with newlines; dict entries
      with ``text`` / ``content`` keys are stringified
    * other types → ``str(content)`` fallback

    Raises :class:`LLMProseError` when the content is ``None`` or an
    unsupported type.
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
    """LLM-backed prose client.

    ``generate_text`` calls ``self.llm.invoke([SystemMessage, HumanMessage])``
    and coerces the response to ``str``. Designed for long-form chapter
    drafts; the caller is responsible for token-budgeting (see
    :func:`writer.context.prep_context` for the canonical context packer).
    """

    name: str = "real"

    def __init__(self, llm: BaseChatModel) -> None:
        self._llm = llm

    def generate_text(self, *, system: str, user: str) -> str:
        try:
            response = self._llm.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
        except Exception as exc:  # noqa: BLE001 — surface as domain exception
            raise LLMProseError(f"LLM 调用失败: {exc}") from exc
        if not isinstance(response, AIMessage):
            raise LLMProseError(
                f"LLM 返回了非 AIMessage: {type(response).__name__}"
            )
        return _coerce_ai_message_to_text(response)


@dataclass
class DeterministicProseClient:
    """Offline prose client.

    Produces structured prose (≥ 200 chars) from the prep_context canon
    / history blocks plus the user message — no LLM call, no network.
    Intended for tests, CI, and dev environments without an API key.

    The output follows a deterministic 3-beat template:

    * chapter heading line (``# 第 <id> 章 <task summary>``)
    * opening paragraph (canon summary)
    * conflict paragraph (history summary)
    * closing hook paragraph

    ``prep_context_fn`` defaults to :func:`writer.context.prep_context`
    but can be overridden in tests for fake context packs.
    """

    name: str = "deterministic"
    prep_context_fn: Callable[..., Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.prep_context_fn is None:
            # Lazy import: ``writer.context`` itself does no heavy I/O
            # at import time, but the prose module is imported early in
            # the engine stack — keep the import inside ``__post_init__``
            # so test-only code paths that construct a
            # ``DeterministicProseClient(prep_context_fn=fake)`` never
            # touch ``writer.context`` at all.
            from writer.context import prep_context

            self.prep_context_fn = prep_context

    def generate_text(self, *, system: str, user: str) -> str:
        # ``user`` is the per-call user message (carries ``task:`` from
        # the workflow); ``system`` is the prep_context system_block.
        # Extract the chapter_id + task from the user message using a
        # small, stable parser so the template is deterministic.
        chapter_id, task_summary = _parse_user_message(user)

        # The prep_context is invoked with the same signature as
        # ``write_chapter._prep_context_node`` so the output looks
        # identical to a Real-mode draft (modulo LLM phrasing).
        pack = self.prep_context_fn(
            chapter_id,
            task_summary or user,
            project_root=None,
            max_tokens=8_000,
        )

        canon = _excerpt(pack.canon_block, limit=200)
        history = _excerpt(pack.history_block, limit=200)
        title = _chapter_title(chapter_id, task_summary)

        # 5-paragraph template: heading + opening + conflict + body + hook.
        # The template is intentionally padded with prose so the assembled
        # text is reliably ≥ 200 chars even when the prep_context blocks
        # are empty or the task is a single short word. Real-mode drafts
        # (LLM output) easily clear that bar; the deterministic path is
        # the worst case the tests assert.
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
    """Extract ``(chapter_id, task_summary)`` from a workflow user message.

    The user message format produced by ``_plan_chapter_node`` is:

    .. code-block:: text

        chapter_id: <id>
        task: <task description>

    For any other format, we fall back to ``("1.1", user)`` so the
    Deterministic client never raises on unexpected input.
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
    """Return the first ``limit`` characters of ``text`` collapsed to one line."""
    if not text:
        return "（暂无上下文）"
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _chapter_title(chapter_id: str, task_summary: str) -> str:
    """Build a deterministic chapter heading like ``第 1.1 章 <task>``."""
    task = task_summary.strip() or "本章"
    # Cap task length to keep titles reasonable.
    if len(task) > 24:
        task = task[:24] + "..."
    return f"第 {chapter_id} 章 {task}"


__all__ = [
    "DeterministicProseClient",
    "LLMProseClient",
    "LLMProseError",
    "RealProseClient",
]
