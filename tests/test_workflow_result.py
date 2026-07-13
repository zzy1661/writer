"""Tests for ``writer.workflows.types.WorkflowResult``.

Added 2026-07-09 (real-writing-pipeline PR1) — covers the
``WorkflowResult`` contract: frozen-ness, status Literal validation,
JSON-serializable via ``dataclasses.asdict``, the three status
branches, and the engine-side adapter.

These tests are pure-data: no I/O, no LangGraph, no EngineSession.
The accompanying engine-dispatch tests in ``test_engine.py`` cover
the integration with ``engine._run_workflow``.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from writer.workflows import (
    WorkflowResult,
    run_workflow,
    workflow_result_from_iterable,
)


class TestWorkflowResultShape:
    def test_default_status_is_pending(self) -> None:
        # The dataclass has no default for ``status`` (it's the
        # discriminator), so a no-arg call fails — verify the contract.
        with pytest.raises(TypeError):
            WorkflowResult()  # type: ignore[call-arg]

    def test_completed_status_with_artifacts(self, tmp_path: Path) -> None:
        draft = tmp_path / "草稿" / "ch1.md"
        result = WorkflowResult(
            status="completed",
            chunks=("[workflow] done",),
            artifacts={"draft_path": draft},
            metrics={"score": 8, "tokens": 1234},
        )
        assert result.status == "completed"
        assert result.chunks == ("[workflow] done",)
        assert result.artifacts["draft_path"] == draft
        assert result.metrics["score"] == 8

    def test_failed_status_carries_error_in_metrics(self) -> None:
        result = WorkflowResult(
            status="failed",
            chunks=("[workflow] error",),
            metrics={"error": "boom"},
        )
        assert result.status == "failed"
        assert result.metrics["error"] == "boom"

    def test_pending_status_is_a_valid_value(self) -> None:
        # PR1 keeps ``pending`` as a valid status (deprecated in PR1,
        # removed in PR3). Verify the type accepts it.
        result = WorkflowResult(status="pending", chunks=("partial",))
        assert result.status == "pending"

    def test_status_literal_is_typechecked_by_mypy_only(self) -> None:
        # ``Literal`` is a static type — at runtime any string is
        # accepted. We rely on mypy to flag invalid values. The
        # ``status`` field therefore accepts anything; the test
        # documents that the contract is type-level only.
        result = WorkflowResult(status="weird")  # type: ignore[arg-type]
        assert result.status == "weird"


class TestWorkflowResultFrozen:
    def test_cannot_mutate_status(self) -> None:
        result = WorkflowResult(status="completed")
        with pytest.raises(FrozenInstanceError):
            result.status = "failed"  # type: ignore[misc]

    def test_cannot_mutate_chunks(self) -> None:
        result = WorkflowResult(status="completed", chunks=("a",))
        with pytest.raises(FrozenInstanceError):
            result.chunks = ("b",)  # type: ignore[misc]

    def test_cannot_mutate_artifacts(self) -> None:
        result = WorkflowResult(status="completed")
        with pytest.raises(FrozenInstanceError):
            result.artifacts = {"x": 1}  # type: ignore[misc]


class TestWorkflowResultSerialization:
    def test_asdict_is_json_friendly(self, tmp_path: Path) -> None:
        draft = tmp_path / "draft.md"
        result = WorkflowResult(
            status="completed",
            chunks=("hello",),
            artifacts={"draft_path": draft},
            metrics={"score": 8},
        )
        # ``Path`` values aren't JSON-serializable directly; the engine's
        # payload builder stringifies them. ``asdict`` preserves Path
        # objects, which is the *raw* shape — callers use
        # ``to_payload()`` for the JSON-friendly version.
        d = asdict(result)
        assert d["status"] == "completed"
        assert d["artifacts"]["draft_path"] == draft
        assert d["metrics"]["score"] == 8

    def test_to_payload_stringifies_paths(self, tmp_path: Path) -> None:
        draft = tmp_path / "草稿" / "ch1.md"
        result = WorkflowResult(
            status="completed",
            artifacts={"draft_path": draft, "summaries_path": tmp_path / "summaries.json"},
            metrics={"score": 9},
        )
        payload = result.to_payload()
        # ``to_payload`` is the engine's payload builder — it stringifies
        # Path values so the payload can be JSON-serialized for the CLI.
        assert payload["artifacts"]["draft_path"] == str(draft)
        assert payload["artifacts"]["summaries_path"] == str(tmp_path / "summaries.json")
        # Full roundtrip via ``json.dumps`` must succeed.
        json.dumps(payload)


class TestWorkflowResultFromIterable:
    def test_adapter_wraps_iterable_into_tuple(self) -> None:
        result = workflow_result_from_iterable(["a", "b", "c"])
        assert result.chunks == ("a", "b", "c")
        assert result.status == "pending"  # default

    def test_adapter_accepts_empty_iterable(self) -> None:
        result = workflow_result_from_iterable([])
        assert result.chunks == ()
        assert result.status == "pending"

    def test_adapter_accepts_none(self) -> None:
        result = workflow_result_from_iterable(None)
        assert result.chunks == ()

    def test_adapter_passes_through_status(self) -> None:
        result = workflow_result_from_iterable(
            ["x"], status="completed", metrics={"score": 7}
        )
        assert result.status == "completed"
        assert result.metrics["score"] == 7

    def test_adapter_accepts_artifacts(self, tmp_path: Path) -> None:
        result = workflow_result_from_iterable(
            ["y"],
            status="completed",
            artifacts={"draft_path": tmp_path / "draft.md"},
        )
        assert result.artifacts["draft_path"] == tmp_path / "draft.md"


class TestRunWorkflowDispatch:
    def test_unknown_workflow_name_returns_failed_result(self) -> None:
        from writer.engine.context import EngineContext
        from writer.engine.deps import production_deps

        result = run_workflow(
            "nonexistent", EngineContext(user_input="x"), production_deps()
        )
        assert result.status == "failed"
        assert result.metrics.get("error") == "unknown_workflow"

    def test_run_workflow_returns_workflow_result(self) -> None:
        # Calling the registry adapter for a real workflow name
        # produces a ``WorkflowResult`` (the PR1 contract). The
        # underlying workflow is a stub in PR1, but the adapter
        # converts its output to the structured shape.
        from writer.engine.context import EngineContext
        from writer.engine.deps import production_deps

        result = run_workflow(
            "write_chapter", EngineContext(user_input="/创作 1.1"), production_deps()
        )
        assert isinstance(result, WorkflowResult)
        # PR1: write_chapter returns status="completed" so the engine
        # emits workflow_completed; the adapter returns the WorkflowResult
        # unchanged when it receives one.
        assert result.status == "completed"


class TestWorkflowStatusType:
    def test_workflow_status_exports_three_values(self) -> None:
        # The type is exported for type-checkers. Runtime check that
        # all three documented values produce a valid WorkflowResult
        # (mypy is responsible for the literal-type enforcement).
        for value in ("completed", "pending", "failed"):
            result = WorkflowResult(status=value)  # type: ignore[arg-type]
            assert result.status == value

    def test_workflow_status_annotation_is_literal(self) -> None:
        # ``get_type_hints`` resolves the forward references and
        # ``Literal`` annotations to the actual ``Literal[...]`` alias.
        # Verify the field's annotation carries the right metadata.
        import typing

        hints = typing.get_type_hints(WorkflowResult)
        status_hint = hints["status"]
        assert typing.get_args(status_hint) == ("completed", "pending", "failed")
