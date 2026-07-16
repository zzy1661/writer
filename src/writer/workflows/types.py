"""结构化返回契约 + Pydantic 审阅模型。

工作流（例如 ``write_chapter``、``review_chapter``）返回
:class:`WorkflowResult` 而非裸 ``Iterable[str]``，让引擎能基于
``status`` 路由到正确的 ``Done`` reason，确定性地在 CLI 中暴露
``artifacts``，并把 ``metrics`` 发送给下游消费者。

PR3 Pydantic 模型（``ReviewVerdict`` / ``MultiConcernReview` /
``ConcernVerdict``）位于本模块，让所有工作流侧的值对象集中一处。

2026-07-09 增补（real-writing-pipeline）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal  # noqa: F401  (Any used in to_payload)

from pydantic import BaseModel, Field

WorkflowStatus = Literal["completed", "pending", "failed"]


@dataclass(frozen=True)
class WorkflowResult:
    """:meth:`RunnerDeps.run_workflow` 的结构化返回值。

    字段：

    * ``status`` —— ``"completed" | "pending" | "failed"`` 之一；引擎把
      它映射到 ``DoneReason``（分别是 ``workflow_completed`` /
      ``aborted`` [针对 pending-rewrite] / ``aborted`` [针对 failure]）。
      ``workflow_pending`` 不再是合法的 ``DoneReason``（PR3 中删除）。
    * ``chunks`` —— 面向 UI 的文本流（不可变 tuple，与
      ``@dataclass(frozen=True)`` 配合良好）。
    * ``artifacts`` —— 工作流产出的路径（``draft_path``、
      ``review_path``、``summaries_path``）。值是 ``Path``，让引擎
      和 CLI 知道这些是文件系统引用而非标签。
    * ``metrics`` —— 数值或字符串遥测（``score``、``retry_count``、
      ``decision``、``error``）。无嵌套 dict / 对象；只接受扁平
      ``float | int | str``，让值能通过 :func:`dataclasses.asdict`
      友好 JSON 序列化。
    """

    status: WorkflowStatus
    chunks: tuple[str, ...] = ()
    artifacts: dict[str, Path] = field(default_factory=dict)
    metrics: dict[str, float | int | str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """渲染为 JSON 友好的 ``Done.payload`` dict。

        引擎在构造终结 :class:`writer.runner.events.Done` 时调用。
        ``artifacts`` 中的 ``Path`` 值被转换为 ``str``，让 payload
        不需要调用方做转换即可 JSON 序列化。
        """

        return {
            "status": self.status,
            "artifacts": {k: str(v) for k, v in self.artifacts.items()},
            "metrics": dict(self.metrics),
        }


def workflow_result_from_iterable(
    chunks_iter: Any,
    *,
    status: WorkflowStatus = "pending",
    artifacts: dict[str, Path] | None = None,
    metrics: dict[str, float | int | str] | None = None,
) -> WorkflowResult:
    """旧 ``Iterable[str]`` 工作流 callable 的适配器。

    :class:`RunnerDeps` 默认实现把已注册的
    :data:`writer.workflows.WORKFLOWS` 条目（PR1 中仍是
    ``Callable[[RunnerContext], Iterable[str]]``）映射到
    :class:`WorkflowResult`，让引擎能基于 ``status`` 派发。默认
    status 为 ``"pending"``，因为旧 callable 没有
    "completed / failed" 概念 —— PR2 / PR3 重写的 ``write_chapter``
    和 ``review_chapter`` 把 callable 替换为显式的 ``WorkflowResult``
    返回。
    """

    chunks = tuple(chunks_iter or ())
    return WorkflowResult(
        status=status,
        chunks=chunks,
        artifacts=artifacts or {},
        metrics=metrics or {},
    )


# ---------------------------------------------------------------------------
# Pydantic 审阅模型（PR3）
# ---------------------------------------------------------------------------


class ReviewVerdict(BaseModel):
    """``write_chapter`` review gate 的结构化判定。

    Pydantic 强制 ``score`` 0..10 且 ``concerns`` 为 list，让
    JSON-prompt 路径（DeepSeek）与原生 ``bind_tools`` 路径（OpenAI）
    都产出经过校验的对象。``pass_`` 字段使用下划线后缀是因为
    Pydantic v2 把 ``pass`` 保留给 ``populate_by_name`` alias
    （以及 ``from_attributes`` re-export）；我们通过 ``model_validate``
    接受 dict 形态 ``{"pass": True}``。
    """

    model_config = {"populate_by_name": True}

    pass_: bool = Field(alias="pass")
    score: int = Field(ge=0, le=10)
    concerns: list[str] = Field(default_factory=list)


class ConcernVerdict(BaseModel):
    """:class:`MultiConcernReview` 中的每个 concern 判定。

    PR3 中用于三个 review concern（``continuity``、``pacing``、
    ``prose``）。每个 concern 有自己的 score（0..10）、pass 标志，
    以及 reviewer 产出的自由形式发现列表。
    """

    model_config = {"populate_by_name": True}

    score: int = Field(ge=0, le=10)
    pass_: bool = Field(alias="pass")
    findings: list[str] = Field(default_factory=list)


class MultiConcernReview(BaseModel):
    """单次结构化 LLM 调用返回的 3 个 review concern。

    按 PR3 设计：单次 ``invoke_structured_json`` 调用产出全部三个
    concern 在同一 Pydantic schema 中，避免 3 次并行 LLM 调用的成本，
    同时仍要求模型覆盖每个 concern（Pydantic schema 校验强制字段）。

    ``total_score`` 由 :class:`review_chapter.aggregate_reviews` 从
    三个 concern score 计算；LLM 被要求提供它，但我们重算作为健全
    性检查。
    """

    continuity: ConcernVerdict
    pacing: ConcernVerdict
    prose: ConcernVerdict
    total_score: int = Field(ge=0, le=10)
    summary: str = Field(default="")


# 决策映射（来自 writing-pipeline spec）：
#   total_score >= 8 AND 所有 concern 通过  -> "pass"
#   total_score >= 6                          -> "tweak"
#   total_score < 6 OR 任意 concern score < 4  -> "needs_rewrite"
DECISION_PASS_THRESHOLD = 8
DECISION_TWEAK_THRESHOLD = 6
DECISION_NEEDS_REWRITE_CONCERN = 4


__all__ = [
    "DECISION_NEEDS_REWRITE_CONCERN",
    "DECISION_PASS_THRESHOLD",
    "DECISION_TWEAK_THRESHOLD",
    "ConcernVerdict",
    "MultiConcernReview",
    "ReviewVerdict",
    "WorkflowResult",
    "WorkflowStatus",
    "workflow_result_from_iterable",
]
