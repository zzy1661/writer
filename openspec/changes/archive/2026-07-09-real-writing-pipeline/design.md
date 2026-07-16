## Context

The writer-agent CLI is structurally complete (REPL, router, engine, agents, tools, skills) but the two long-task workflows at the heart of the writing loop are stubs:

- `write_chapter` runs a real LangGraph state machine (`prep_context → write_chapter → proofread → review_gate → (rewrite | END)`) but `_write_chapter_node` only ever produces a fixed template string containing the literal `"正文占位"`. No actual prose is generated; nothing is written to `manuscript/`.
- `review_chapter` is a one-function stub returning 3 lines of "TODO" prose. No reviewer, no report, no persistence.
- `engine._run_workflow` terminates every workflow turn with `Done(reason="workflow_pending")` regardless of what the workflow did, so users see "pending" forever even when the workflow ran successfully.

The project baseline is **366 passing tests** (2026-07-09), `ruff` + `mypy` clean, and the existing `LLMToolLoop` already supports structured-output and tool-calling paths for short prompts. What's missing is a long-form prose generation path distinct from the tool-calling loop, and a structured return contract for workflows so the engine can route on real outcomes.

This change delivers the real writing pipeline in 3 incremental PRs. Each PR keeps the test baseline green and the existing public API surface stable (no CLI flag day). The changes touch 3 layers of the 4-layer architecture:

- **L2 engine** (PR1): `WorkflowResult` Protocol return, new `DoneReason = "workflow_completed"`, `_run_workflow` dispatch on `status`
- **L3 workflows** (PR1+PR2+PR3): both `write_chapter` and `review_chapter` rewritten to return real `WorkflowResult` instances backed by LangGraph state machines
- **L3 llm** (PR2): new `LLMProseClient` Protocol + Real / Deterministic implementations

## Goals / Non-Goals

**Goals:**

- `/创作 [chapter_id] [要求...]` produces real prose (≥ 200 chars of structured chapter content), persists to `manuscript/chapter-<id>.md`, updates `chapter_summaries.json`, and ends in `Done(reason="workflow_completed")` with `artifacts` and `metrics` in the payload.
- `/审核 [chapter_id]` produces a structured review report (continuity / pacing / prose concerns, total score, decision), persists to `manuscript/reviews/chapter-<id>-<ts>.json`, and ends in `Done(reason="workflow_completed")`.
- The two workflows reuse the existing `foreshadow_search` tool (from `chg-remove-rag`) for continuity checking.
- Both workflows work offline (no API key) via `DeterministicProseClient` so the 366-test baseline stays green and the system is usable without network.
- `Done(reason="workflow_pending")` is deprecated in PR1 and removed in PR3 — every shipped workflow always returns a real `status` in `{completed, failed}`.
- 366-test baseline remains green after every PR.

**Non-Goals:**

- True parallel LLM calls for the 3 review concerns (deferred to a follow-up change; PR3 uses 1 structured call returning all 3).
- Genre-aware write/review prompts (current: single prompt template; the existing `fea-genre-aware-init` change already separates agent prompt bodies, but write/review stay genre-agnostic in this change).
- Threshold tuning for `review_gate` (PR2 fixes 7; tuning is a separate change).
- Token-budget-aware chapter splitting for very long drafts (current: single LLM call per draft; long chapters may exceed context window in adversarial cases).
- Hot-reload of `chapter_summaries.json` in REPL across turns (the canon block reads it on demand per turn, which is sufficient).
- Web UI / streaming token display (current engine streams `TextChunk`; we keep that contract).
- Removing the `agent/` compat layer (separate change).

## Decisions

### Decision 1: `WorkflowResult` is a `@dataclass(frozen=True)`, not a Pydantic model

**Rationale:** The engine's event types (`TextChunk`, `ActionEvent`, `ToolCall`, `Done`, etc.) are all `@dataclass(frozen=True)`. `WorkflowResult` is a similar value object that flows across the engine boundary. Using `dataclass` keeps the file `events.py`-consistent and avoids Pydantic's heavier machinery (validators, serialization options) for what is essentially a tagged union. The single counter-example is `AgentAction`, which is a Pydantic model — but `AgentAction` is a router output that downstream code may `.model_copy(update=...)`, which is a Pydantic idiom. `WorkflowResult` has no such need.

**Alternatives considered:**
- **Pydantic `BaseModel` with `model_config={"frozen": True}`**: more consistent with `AgentAction`, but introduces Pydantic imports into the workflows package and yields no concrete benefit.
- **`TypedDict`**: too loose; doesn't enforce field presence at construction time, and `EngineDeps` callers would silently return wrong shapes.

### Decision 2: `EngineDeps.run_workflow` changes signature in one PR (no compat shim)

**Rationale:** There are exactly 2 callers (`write_chapter.run` and `review_chapter.stub`) and both are updated in PR1 alongside the Protocol change. A compat shim that accepted both `Iterable[str]` and `WorkflowResult` would obscure the new contract and force every test stub to decide which shape to return. The 366-test baseline includes `PlainDeps` and similar Protocol stubs that already get updated when `EngineDeps` gains fields (per the memory note "Protocol 字段扩展后会破坏现有 stub"). Doing the same in this PR is consistent with that established pattern.

**Alternatives considered:**
- **Dual-state return** (`Iterable[str] | WorkflowResult`): adds type complexity, requires runtime `isinstance` checks, and saves no real work since both impls are touched in PR1.
- **Keep `Iterable[str]` and add a separate `result: WorkflowResult` field**: makes the return type noisy (`def run_workflow(...) -> tuple[Iterable[str], WorkflowResult]`) and doesn't match existing patterns.

### Decision 3: `LLMProseClient` is a Protocol, not an ABC

**Rationale:** Mirrors the existing `IntentRouter` / `Tool` patterns. The Protocol lets `RealProseClient` and `DeterministicProseClient` be unrelated classes (different constructors, different field types) while still passing `isinstance(x, LLMProseClient)` checks via `@runtime_checkable`. The `name: str` attribute is required so `production_deps` and tests can branch on the implementation without importing the concrete class.

**Alternatives considered:**
- **Abstract base class with `@abstractmethod`**: heavier; requires explicit subclass registration. The Protocol approach lets `production_deps` decide at runtime.
- **Single class with `use_real_llm: bool` flag**: harder to test, mixes real and fake behavior in one class, makes `client.name` meaningless.

### Decision 4: `DeterministicProseClient` returns structured prose, not a one-liner

**Rationale:** The current placeholder is a single fixed string with "正文占位". If we ship `DeterministicProseClient` that returns a one-liner, the offline tests pass but the UX is bad — `/创作` in a no-API-key dev environment still produces a one-line stub. Instead, the deterministic path assembles prose from `prep_context` canon/history blocks plus a deterministic beat list (e.g., "开场 → 冲突 → 高潮 → 收束 → 钩子") and a fixed template body. Output is ≥ 200 chars of structured chapter content with a heading, 2+ body paragraphs, and an end hook. This is what offline tests assert and what users see in dev.

**Alternatives considered:**
- **Return empty string in deterministic mode**: forces callers to handle empty drafts (bad UX, breaks `proofread`'s `< 80 chars` warning).
- **Return a static template string**: simpler but produces the same output for every chapter, making tests less meaningful.
- **Generate a tiny random text**: non-deterministic, breaks the "deterministic" contract.

### Decision 5: `chapter_summaries.append_summary` is a direct helper, not a `safe_write_file` mode

**Rationale:** `safe_write_file` is a Tool consumed by the LLM tool loop. `append_summary` is a direct function called from `persist_outputs` (a workflow node), and it needs:
- Atomic guarantees (tempfile + `os.replace`)
- Read-modify-write of a JSON file (impossible with `safe_write_file`'s `create | overwrite | append` modes for JSON arrays)
- Project-root validation independent of the Tool layer

A direct helper at `writer.project.chapter_summaries` is independently testable (per the writer-tools spec scenario "append_summary works in test isolation") and doesn't bloat the Tool layer with one-off modes.

**Alternatives considered:**
- **Add `mode="append_json"` to `safe_write_file`**: would couple the JSON read-modify-write logic into the Tool layer, where it doesn't belong.
- **Use `safe_edit_file` to find-and-replace the closing `]}`**: fragile, breaks if the file's whitespace changes.

### Decision 6: Review gate threshold is fixed at 7, no per-genre tuning

**Rationale:** The 366-test baseline must stay green. A 7/10 threshold is permissive enough that well-formed deterministic drafts and modest LLM outputs both pass; tightening it in PR2 would risk CI flakiness from LLM output variance. Tuning is a separate change that should be driven by a small labeled evaluation set (out of scope here).

**Alternatives considered:**
- **Threshold = 8**: stricter; deterministic path auto-passes at 8, so no impact on offline tests, but LLM drafts with `score=7` would loop, increasing token cost. The number 7 leaves headroom.
- **Per-genre threshold**: requires genre plumbing through the workflow state. The current write/review graphs are genre-agnostic by design; adding genre-awareness here would scope-creep this change.

### Decision 7: Reviewer uses 1 structured LLM call returning 3 concerns, not 3 parallel calls

**Rationale:** A single `invoke_structured_json(MultiConcernReview, ...)` call:
- Halves latency vs 3 sequential calls
- Costs roughly 1/3 of 3 parallel calls (parallel calls charge 3x prompt tokens for the shared context)
- The Pydantic schema with 3 sub-`ConcernVerdict` objects forces the model to address all 3 concerns (LangChain's structured output guarantees schema compliance)
- The base `MultiConcernReview` prompt is shared across concerns, so we don't lose cross-concern coherence

Deferring 3 parallel calls keeps the PR small and the failure modes simple. A follow-up change can swap in `asyncio.gather` over 3 calls if profiling shows the single call is a bottleneck.

**Alternatives considered:**
- **3 parallel LangGraph nodes, each calling LLM**: more complex graph topology, more failure modes (one concern's failure shouldn't fail the others), and parallel LLM calls double the cost.
- **1 LLM call with free-form prose review, parsed heuristically**: less reliable, requires fragile regex parsing.

### Decision 8: `workflow_pending` is deprecated in PR1, removed in PR3

**Rationale:** PR1 introduces `workflow_completed` and updates both `write_chapter` and `review_chapter` to return real `WorkflowResult` values. The deprecation path:
- **PR1**: `workflow_pending` is still emitted when a workflow returns `status="pending"`, BUT the engine also yields a deprecation `TextChunk` so users (and our own tests) see the warning.
- **PR3**: `workflow_pending` is removed from the `DoneReason` Literal. Tests asserting `workflow_pending` MUST be updated; mypy catches stragglers.

A 2-PR deprecation window lets tests migrate incrementally and surfaces any forgotten callers via the warning.

**Alternatives considered:**
- **Remove in PR1**: breaks every test that asserts the current behavior in one shot.
- **Keep forever**: leaves a footgun where new workflows can "ship" by returning `pending` and pretending to be incomplete.

### Decision 9: `writer.workflows.params` owns `/创作` / `/审核` argument parsing

**Rationale:** These two commands dispatch to workflows (not SKILL.md directives), so the workflow layer is the natural owner of argument parsing. A `WorkflowParams` Protocol + `extract_*` functions:
- Are pure functions, independently testable
- Don't require a `WriterState` or `EngineContext`
- Live next to the workflow that uses them (no cross-package dependency)

**Alternatives considered:**
- **Parse in `_write_chapter_node` directly**: tightly couples parsing to the node; harder to test in isolation.
- **Parse in `cli/main.py`**: violates the project's "REPL 路由原则" (CLI doesn't parse workflow args).

## Risks / Trade-offs

**[Risk]** LLM drafts vary in length/quality; the `proofread` node's 80-char warning may fire spuriously.
→ **Mitigation**: The deterministic path always produces ≥ 200 chars; the LLM path is prompted to produce ≥ 500 chars. The proofread node is a warning, not a blocker, so even a short draft proceeds.

**[Risk]** `chapter_summaries.append_summary` JSON shape may conflict with an existing field used by `chg-remove-rag`'s canon block.
→ **Mitigation**: The canon block reads `chapter_summaries.json` as a generic dict today. The new shape uses `{"chapters": [{"chapter_id": ..., "summary": ..., "written_at": ...}]}`. If the existing file has a different shape, the helper detects it and migrates by wrapping the legacy entries under `{"chapters": [...], "_legacy": ...}`. Verified in PR2's tests.

**[Risk]** `DeterministicProseClient` drifts from `RealProseClient` output, causing the "happy path" UX to differ depending on API key presence.
→ **Mitigation**: The two clients share the same prompt structure (canon + history → chapter body); only the response generation differs. Tests assert both clients produce drafts with the same minimum structure (heading + 2 paragraphs + hook). The 5% UX drift is acceptable for offline dev.

**[Risk]** PR1's Protocol signature change breaks every `PlainDeps`-style test stub in the repo, not just `test_engine_session.py`.
→ **Mitigation**: Same pattern that worked for the existing memory note ("Protocol 字段扩展后会破坏现有 stub"). Run `uv run pytest` after the change; fix any `PlainDeps` failures; expected ~3-5 stub updates.

**[Risk]** PR3's removal of `workflow_pending` breaks any consumer outside this repo (downstream `IntentRouter`, plugins).
→ **Mitigation**: The `DoneReason` Literal is in `writer.engine.events`; the Literal-mismatch error is a mypy-only signal. Runtime consumers (e.g., REPL renderers) that read `event.reason` as a string won't crash — they'll just hit the unknown-reason branch. The PR3 changelog entry warns downstream consumers.

**[Risk]** Single LLM call returning 3 concerns may produce weaker review quality than 3 focused calls (model may "rush" through concerns).
→ **Mitigation**: The `MultiConcernReview` Pydantic schema lists required fields per concern (≥ 1 finding, score 0-10), forcing structured output. If PR3's review quality proves insufficient, a follow-up change can move to 3 parallel calls with a small refactor (the `aggregate_reviews` node already factors the structure).

**[Risk]** `review_chapter` opens the target chapter file but the user may have not yet written it (chapter_id = 1.3 but only 1.1 exists).
→ **Mitigation**: `load_target_chapter` checks file existence; if missing, returns `WorkflowResult(status="failed", metrics={"error": "chapter_not_found", "chapter_id": ...})` which the engine renders as `Done(reason="aborted", payload={"error": "chapter_not_found"})`. User sees a clear error message.

## Migration Plan

PR1, PR2, PR3 each ship as independent git commits on `main`. No flag day, no parallel maintenance branches. The deprecation window for `workflow_pending` is built in.

- **PR1**: Protocol upgrade. `EngineDeps.run_workflow` signature change + `WorkflowResult` + `DoneReason = "workflow_completed"`. Both workflow functions updated to return minimal-but-real `WorkflowResult` values (still template-ish for the write path, but with `status="completed"` and `artifacts` set to expected paths). CLI adds `case "workflow_completed"` rendering. `_run_workflow` docstring cleanup.
- **PR2**: `LLMProseClient` Protocol + Real + Deterministic. `write_chapter` rewritten to the 5-node graph with real drafting. `chapter_summaries.append_summary` helper added. `EngineDeps.prose_client` wired in `production_deps`. Review gate threshold fixed at 7.
- **PR3**: `review_chapter` rewritten to the 5-node reviewer graph. `MultiConcernReview` Pydantic schema + `DecisionGate` (pass | tweak | needs_rewrite). `workflow_pending` removed from `DoneReason` Literal. `engine._run_workflow` simplified (no deprecation branch).

**Rollback**: Each PR is a single git commit. Reverting a single commit restores the prior state. The deprecation window in PR1 means PR3 can be deferred indefinitely without breaking the engine (PR1's `workflow_pending` branch still works).

## Open Questions

- **`chapter_summaries.json` shape**: existing file (if any) may have keys other than `chapters`. Decision deferred to PR2 task "Audit existing chapter_summaries.json shape in test fixtures".
- **Review report filename collision**: timestamp suffix uses ISO format; if two reviews run within the same second on the same chapter (rare in interactive REPL, possible in batch), the second overwrites the first. Decision: accept the risk for PR3, document in a follow-up.
- **Offline test coverage of `RealProseClient`**: PR2's tests use a recording fake `BaseChatModel` for `RealProseClient` (mirroring the existing `LLMToolLoop` test pattern per memory). No real network calls in CI. Decision confirmed.
- **Genre-aware prompts for `draft_chapter` and `aggregate_reviews`**: not in this change. The `fea-genre-aware-init` change gives us 3 agent body templates; extending the writing pipeline to use them is a separate scoped change.
