## Why

The core writing loop is non-functional. `/创作` (write_chapter) and `/审核` (review_chapter) are the two main user-facing commands for the actual novel-writing workflow, but both end in stub outputs:

- `src/writer/workflows/write_chapter.py:109-123` — `_write_chapter_node` returns a fixed string with "正文占位" instead of real prose. The LangGraph state machine runs but the only thing that ever gets produced is a template.
- `src/writer/workflows/review_chapter.py:15-27` — explicit stub that returns 3 lines describing what the workflow *will* do. No reviewer exists.
- `src/writer/engine/loop.py:447-458` — `_run_workflow` ends every workflow turn with `Done(reason="workflow_pending")` regardless of what the workflow did. Users see "pending" forever.

This change replaces all three with real generation + multi-perspective review + structured persistence, delivered as 3 incremental PRs that each keep the existing 366-test baseline green.

## What Changes

### PR1 — Protocol upgrade (no behavior change for users yet)

- **Add `writer.workflows.types.WorkflowResult`** — frozen dataclass returning a structured outcome (`status: Literal["completed"|"pending"|"failed"]`, `chunks: tuple[str, ...]`, `artifacts: dict[str, Path]`, `metrics: dict[str, float|int|str]`). Replaces the current `Iterable[str]` contract.
- **Change `EngineDeps.run_workflow` Protocol signature** to return `WorkflowResult`. Both `write_chapter.run` and `review_chapter.stub` updated in the same PR. No `Iterable[str]` compat shim — only 2 callers.
- **Add `DoneReason = "workflow_completed"`** to the Literal in `engine/events.py`. Engine `_run_workflow` dispatches on `result.status` and emits `workflow_completed` (status=completed) / `aborted` (status=failed) / keeps `workflow_pending` as deprecated fallback for status=pending.
- **CLI `cli/main.py::_run_engine` adds a `case "workflow_completed"`** rendering `artifacts` + `metrics` in the terminal output (mirrors the `tool_completed` rendering).
- **BREAKING**: `workflow_pending` is marked deprecated in PR1 (kept working) and removed in PR3. `EngineDeps.run_workflow` signature change is a Protocol breaking change — all custom `EngineDeps` implementations must be updated.
- **Update `_run_workflow` docstring** to remove the "stub" wording.

### PR2 — `write_chapter` real generation + persistence

- **Add `writer.llm.prose.LLMProseClient` Protocol** with two implementations: `RealProseClient` (wraps `get_llm()` and calls `llm.invoke([system, user])` returning `str`) and `DeterministicProseClient` (assembles prose from canon/history using existing prep_context blocks, no LLM call).
- **`production_deps` always injects a `LLMProseClient`** (Real when `settings.has_api_key`, Deterministic otherwise). The previous `tool_loop=None` pattern does NOT apply here — the prose client is never `None`, only the choice of implementation differs.
- **Replace `_write_chapter_node`** with: plan_chapter → draft_chapter (uses LLMProseClient) → proofread → review_gate → persist_outputs. Review gate threshold fixed: deterministic path auto-passes; LLM path uses `ReviewVerdict` (Pydantic: `pass: bool`, `score: int 0-10`, `concerns: list[str]`) with `score >= 7` to pass. Threshold tuning deferred to a future PR.
- **Review gate reuses `foreshadow_search`** (the tool from chg-remove-rag) to verify continuity against the project's `伏笔.yaml` ledger.
- **Add `writer.project.chapter_summaries.append_summary`** — typed helper that appends a chapter summary to `chapter_summaries.json` atomically (tempfile + `os.replace`). Used by `persist_outputs` node and is independently testable.
- **Persist to `manuscript/chapter-xxx.md`** with deterministic filename from `chapter_id`. `persist_outputs` writes both the draft and the updated summaries file.
- **Add `writer.workflows.params`** — argument parsing for `/创作 [chapter_id] [要求...]`. Workflow-owned (not directive-owned), lives alongside the workflow.

### PR3 — `review_chapter` multi-perspective review

- **Add `writer.workflows.review_chapter.build_reviewer_graph`** with nodes: `load_target_chapter` → `prep_review_context` → `aggregate_reviews` → `decision_gate` → `persist_review_report`.
- **Single structured LLM call** produces 3 concerns in one Pydantic schema (continuity / pacing / prose). Defer 3 parallel LLM calls to a future optimization PR — the single-call path is cheaper and the structured schema guarantees all 3 concerns are returned.
- **Continuity reviewer reuses `foreshadow_search`** to check each active foreshadow against the draft's context.
- **Decision gate** produces `pass | needs_rewrite | tweak` outcomes. When `needs_rewrite`, return `WorkflowResult(status=pending, metrics={"reason": "needs_rewrite"})` to signal upstream `/创作` to trigger a re-run.
- **Persist `manuscript/reviews/chapter-xxx.json`** with findings + total score.
- **Remove `workflow_pending` DoneReason** entirely. `EngineDeps.run_workflow` callers must always return `completed` or `failed`.

## Capabilities

### New Capabilities

- `workflow-result` — Defines the `WorkflowResult` contract: fields, status values, JSON-friendly serialization shape, and the contract between `EngineDeps.run_workflow` and `engine._run_workflow`.
- `prose-llm` — Defines the `LLMProseClient` Protocol + Real / Deterministic implementations + selection rules in `production_deps`. The contract for long-form prose generation (distinct from the existing structured-output / tool-calling paths).
- `writing-pipeline` — Defines the `write_chapter` and `review_chapter` LangGraph state shapes, node responsibilities, persistence contracts (`manuscript/chapter-xxx.md` + `chapter_summaries.json` + `manuscript/reviews/*.json`), review gate threshold rules, and the `/创作` / `/审核` argument parsing contract (`writer.workflows.params`).

### Modified Capabilities

- `engine-loop` — `DoneReason` literal gains `workflow_completed` (PR1) and loses `workflow_pending` (PR3). `EngineDeps.run_workflow` signature changes from `Iterable[str]` to `WorkflowResult`. Engine `_run_workflow` dispatch logic must read `result.status` and emit the matching `Done` reason.
- `writer-tools` — `chapter_summaries` becomes a write-capable file via the new `writer.project.chapter_summaries` module (atomic append helper). The existing read path (used by `context._build_canon_block`) is unchanged.

## Impact

### Code
- `src/writer/workflows/__init__.py` — re-export `WorkflowResult` + new `params` / `chapter_summaries` modules
- `src/writer/workflows/{types,params,chapter_summaries}.py` — NEW
- `src/writer/workflows/write_chapter.py` — rewrite `run()` to return `WorkflowResult`; replace `_write_chapter_node` with the 5-node graph (PR2)
- `src/writer/workflows/review_chapter.py` — replace stub with `build_reviewer_graph` (PR3)
- `src/writer/llm/prose.py` — NEW (Protocol + Real + Deterministic)
- `src/writer/llm/__init__.py` — re-export `LLMProseClient` / `RealProseClient` / `DeterministicProseClient`
- `src/writer/engine/events.py` — `DoneReason` literal extends, then shrinks in PR3
- `src/writer/engine/deps.py` — `EngineDeps.run_workflow` Protocol signature change
- `src/writer/engine/loop.py` — `_run_workflow` dispatches on `result.status`; docstring cleanup
- `src/writer/cli/main.py` — new `case "workflow_completed"` rendering

### Tests
- `tests/test_workflow_result.py` — NEW (roundtrip + serialization + type tests)
- `tests/test_prose_llm.py` — NEW (Real + Deterministic, selection in `production_deps`)
- `tests/test_workflow_chapter_summaries.py` — NEW (atomic write helper)
- `tests/test_workflows_write_chapter.py` — NEW (graph traversal + persistence + retry loop)
- `tests/test_workflows_review_chapter.py` — NEW (reviewer aggregation + decision gate)
- `tests/test_workflows_params.py` — NEW (command argument parsing)
- `tests/test_engine.py` — update `DoneReason` assertions (PR1: add `workflow_completed`; PR3: drop `workflow_pending`); update `run_workflow` mock to return `WorkflowResult`
- `tests/test_engine_deps.py` — `PlainDeps` / other Protocol stubs update `run_workflow` signature

### Specs (main, after apply)
- `openspec/specs/workflow-result/spec.md` — NEW
- `openspec/specs/prose-llm/spec.md` — NEW
- `openspec/specs/writing-pipeline/spec.md` — NEW
- `openspec/specs/engine-loop/spec.md` — delta (new `workflow_completed` requirement; remove `workflow_pending` in PR3)
- `openspec/specs/writer-tools/spec.md` — delta (atomic `chapter_summaries.append_summary` requirement)

### Dependencies
- No new external dependencies. `langgraph`, `langchain-openai`, `pydantic` are already in `pyproject.toml`.

### Out of scope (deferred to follow-up changes)
- Threshold tuning for `review_gate` (current fixed value: 7)
- True parallel LLM calls for review (current: 1 structured call returning 3 concerns)
- Genre-aware write/review prompts (current: single prompt template)
- Token-budget-aware chapter splitting for very long drafts
- Hot-reload of `chapter_summaries.json` in REPL across turns
