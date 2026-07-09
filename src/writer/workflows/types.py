"""Structured return contract + Pydantic review models.

A workflow (e.g. ``write_chapter``, ``review_chapter``) returns a
:class:`WorkflowResult` instead of a bare ``Iterable[str]`` so the
engine can route on ``status`` to pick the right ``Done`` reason,
surface ``artifacts`` deterministically in the CLI, and ship
``metrics`` to downstream consumers.

The PR3 Pydantic models (``ReviewVerdict`` / ``MultiConcernReview`` /
``ConcernVerdict``) live in this module so all workflow-side value
objects live in one place.

Added 2026-07-09 (real-writing-pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal  # noqa: F401  (Any used in to_payload)

from pydantic import BaseModel, Field

WorkflowStatus = Literal["completed", "pending", "failed"]


@dataclass(frozen=True)
class WorkflowResult:
    """Structured return value of :meth:`EngineDeps.run_workflow`.

    Fields:

    * ``status`` — one of ``"completed" | "pending" | "failed"``; the
      engine maps this to a ``DoneReason`` (``workflow_completed`` /
      ``aborted`` [for pending-rewrite] / ``aborted`` [for failure]
      respectively). ``workflow_pending`` is no longer a valid
      ``DoneReason`` (removed in PR3).
    * ``chunks`` — UI-facing text stream (immutable tuple to play nice
      with ``@dataclass(frozen=True)``).
    * ``artifacts`` — paths the workflow produced (``draft_path``,
      ``review_path``, ``summaries_path``). Values are ``Path`` so the
      engine and CLI know these are filesystem references, not labels.
    * ``metrics`` — numeric or string telemetry (``score``,
      ``retry_count``, ``decision``, ``error``). No nested dicts /
      objects; flat ``float | int | str`` only so the value is
      JSON-friendly via :func:`dataclasses.asdict`.
    """

    status: WorkflowStatus
    chunks: tuple[str, ...] = ()
    artifacts: dict[str, Path] = field(default_factory=dict)
    metrics: dict[str, float | int | str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Render a JSON-friendly ``Done.payload`` dict.

        The engine calls this when constructing the terminal
        :class:`writer.engine.events.Done`. ``Path`` values in
        ``artifacts`` are converted to ``str`` so the payload is
        JSON-serializable without forcing callers to do the
        conversion themselves.
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
    """Adapter for legacy ``Iterable[str]`` workflow callables.

    The :class:`EngineDeps` default impl maps registered
    :data:`writer.workflows.WORKFLOWS` entries (which are still
    ``Callable[[EngineContext], Iterable[str]]`` in PR1) into
    :class:`WorkflowResult` so the engine can dispatch on
    ``status``. The default status is ``"pending"`` because the
    legacy callables had no concept of "completed / failed" — the
    PR2 / PR3 rewrites of ``write_chapter`` and ``review_chapter``
    replace the callables with explicit ``WorkflowResult`` returns.
    """

    chunks = tuple(chunks_iter or ())
    return WorkflowResult(
        status=status,
        chunks=chunks,
        artifacts=artifacts or {},
        metrics=metrics or {},
    )


# ---------------------------------------------------------------------------
# Pydantic review models (PR3)
# ---------------------------------------------------------------------------


class ReviewVerdict(BaseModel):
    """Structured verdict from the ``write_chapter`` review gate.

    Pydantic enforces ``score`` 0..10 and ``concerns`` as a list so
    the JSON-prompt path (DeepSeek) and the native ``bind_tools`` path
    (OpenAI) both produce a validated object. The ``pass_`` field uses
    a trailing underscore because Pydantic v2 reserves ``pass`` for the
    ``populate_by_name`` alias (and ``from_attributes`` re-export);
    we accept the dict form ``{"pass": True}`` via ``model_validate``.
    """

    model_config = {"populate_by_name": True}

    pass_: bool = Field(alias="pass")
    score: int = Field(ge=0, le=10)
    concerns: list[str] = Field(default_factory=list)


class ConcernVerdict(BaseModel):
    """Per-concern verdict inside a :class:`MultiConcernReview`.

    Used for the three review concerns in PR3 (``continuity``,
    ``pacing``, ``prose``). Each concern has its own score (0..10),
    pass flag, and a list of free-form findings the reviewer
    produced.
    """

    model_config = {"populate_by_name": True}

    score: int = Field(ge=0, le=10)
    pass_: bool = Field(alias="pass")
    findings: list[str] = Field(default_factory=list)


class MultiConcernReview(BaseModel):
    """Single structured LLM call returning 3 review concerns.

    Per the PR3 design: a single ``invoke_structured_json`` call
    produces all three concerns in one Pydantic schema, avoiding the
    cost of 3 parallel LLM calls while still requiring the model to
    address each concern (Pydantic schema validation enforces the
    fields).

    ``total_score`` is computed in :class:`review_chapter.aggregate_reviews`
    from the three concern scores; the LLM is asked to provide it but
    we recompute as a sanity check.
    """

    continuity: ConcernVerdict
    pacing: ConcernVerdict
    prose: ConcernVerdict
    total_score: int = Field(ge=0, le=10)
    summary: str = Field(default="")


# Decision mapping (from the writing-pipeline spec):
#   total_score >= 8 AND all concerns pass  -> "pass"
#   total_score >= 6                          -> "tweak"
#   total_score < 6 OR any concern score < 4  -> "needs_rewrite"
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
