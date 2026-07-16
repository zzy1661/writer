# workflow-result Specification

## Purpose
TBD - created by archiving change real-writing-pipeline. Update Purpose after archive.
## Requirements
### Requirement: WorkflowResult is a frozen dataclass with status / chunks / artifacts / metrics

The system SHALL define `writer.workflows.types.WorkflowResult` as a `@dataclass(frozen=True)` with exactly these four fields:

- `status: Literal["completed", "pending", "failed"]`
- `chunks: tuple[str, ...]` (immutable stream of UI-facing text; empty tuple is allowed)
- `artifacts: dict[str, Path]` (paths the workflow produced; defaults to empty dict)
- `metrics: dict[str, float | int | str]` (numeric or string telemetry; defaults to empty dict)

The type MUST be JSON-serializable via `dataclasses.asdict` (all field types are JSON-friendly).

#### Scenario: completed workflow carries artifacts and metrics
- **WHEN** a workflow returns `WorkflowResult(status="completed", chunks=("[workflow] done",), artifacts={"draft_path": Path("manuscript/ch1.md")}, metrics={"score": 8, "tokens": 1234})`
- **THEN** the engine MUST emit `Done(reason="workflow_completed", payload={"workflow": name, "artifacts": {"draft_path": "manuscript/ch1.md"}, "metrics": {"score": 8, "tokens": 1234}})`

#### Scenario: failed workflow becomes an aborted Done
- **WHEN** a workflow returns `WorkflowResult(status="failed", chunks=("[workflow] error",), metrics={"error": "..."})`
- **THEN** the engine MUST emit `Done(reason="aborted", payload={"workflow": name, "error": "..."})`

#### Scenario: pending workflow surfaces a deprecation warning
- **WHEN** a workflow returns `WorkflowResult(status="pending", chunks=("[workflow] partial",))`
- **THEN** the engine MUST emit `Done(reason="workflow_pending", payload={"workflow": name})` AND a deprecation `TextChunk` whose text starts with `"[engine] workflow_pending 已废弃"` describing that callers should return `completed` or `failed`

#### Scenario: WorkflowResult is frozen
- **WHEN** a caller attempts `result.status = "completed"` on an existing `WorkflowResult`
- **THEN** the assignment MUST raise `dataclasses.FrozenInstanceError`

### Requirement: workflow_completed DoneReason is exported

The `DoneReason` Literal in `writer.engine.events` SHALL include the value `"workflow_completed"`. After PR1 the full set is:

```text
answered | command_pending | tool_pending | workflow_pending | ask_user | aborted | tool_completed | workflow_completed
```

After PR3 (final state) the set is:

```text
answered | command_pending | tool_pending | ask_user | aborted | tool_completed | workflow_completed
```

`workflow_pending` is deprecated in PR1 and removed in PR3.

#### Scenario: DoneReason literal contains workflow_completed
- **WHEN** a consumer runs `from writer.engine.events import DoneReason` after PR1 is applied
- **THEN** `DoneReason` MUST be a Literal whose valid string values include `"workflow_completed"`

#### Scenario: workflow_pending is no longer a valid value after PR3
- **WHEN** a workflow or test attempts to construct `Done(reason="workflow_pending", ...)` after PR3 is applied
- **THEN** mypy MUST reject the construction with a Literal-mismatch error

### Requirement: RunnerDeps.run_workflow returns WorkflowResult

The `EngineDeps.run_workflow` Protocol method SHALL have signature `def run_workflow(self, name: str, ctx: EngineContext) -> WorkflowResult`. The default implementation in `src/writer/engine/deps.py` MUST look up the workflow in `writer.workflows.WORKFLOWS` and adapt the legacy `Iterable[str]` callable shape (via a wrapper) so existing workflow callables continue to compile but their return values are mapped to `WorkflowResult(status="pending", chunks=tuple(result))`.

#### Scenario: custom EngineDeps implementation matches the new Protocol
- **WHEN** a test defines a `PlainDeps` Protocol stub with `def run_workflow(self, name, ctx) -> WorkflowResult: return WorkflowResult(status="completed", chunks=())`
- **THEN** `isinstance(stub, EngineDeps)` MUST be True

#### Scenario: unknown workflow name still produces a useful WorkflowResult
- **WHEN** `deps.run_workflow("nonexistent_workflow", ctx)` is called
- **THEN** it MUST return `WorkflowResult(status="failed", chunks=("[workflow] 未知工作流 'nonexistent_workflow'",), metrics={"error": "unknown_workflow"})`

