## 1. PR1 — Protocol upgrade (WorkflowResult + workflow_completed)

- [x] 1.1 Create `src/writer/workflows/types.py` with `@dataclass(frozen=True) WorkflowResult` per workflow-result spec. Fields: `status: Literal["completed","pending","failed"]`, `chunks: tuple[str, ...]`, `artifacts: dict[str, Path]`, `metrics: dict[str, float | int | str]`. Re-export from `src/writer/workflows/__init__.py`.

- [x] 1.2 Add `"workflow_completed"` to the `DoneReason` Literal in `src/writer/engine/events.py`. Verify with `uv run mypy src/writer` (no errors).

- [x] 1.3 Change `EngineDeps.run_workflow` Protocol signature in `src/writer/engine/deps.py` from `Iterable[str]` to `WorkflowResult`. Update the default implementation in the `EngineDeps` Protocol (line 124 area) and the `@dataclass class EngineDeps` default field impl (line 240 area). Add a thin wrapper helper `_workflows_runner(name, ctx) -> WorkflowResult` that maps legacy `Iterable[str]` callables to `WorkflowResult(status="pending", chunks=tuple(result))`.

- [x] 1.4 Update `engine._run_workflow` in `src/writer/engine/loop.py` (lines 447-458) to:
  - Call `result = deps.run_workflow(name, ctx)` and yield each `result.chunks` item as a `TextChunk`
  - On `result.status == "completed"`: yield `Done(reason="workflow_completed", payload={"workflow": name, "artifacts": {k: str(v) for k,v in result.artifacts.items()}, "metrics": result.metrics})`
  - On `result.status == "failed"`: yield `Done(reason="aborted", payload={"workflow": name, "error": result.metrics.get("error", "")})`
  - On `result.status == "pending"`: yield a deprecation `TextChunk(text="[engine] workflow_pending 已废弃,改用 workflow_completed / aborted\n")` then `Done(reason="workflow_pending", payload={"workflow": name})` (PR3 removes the pending branch)
  - Update the docstring to remove the word "stub"

- [x] 1.5 Update `src/writer/workflows/write_chapter.py::run` to return `WorkflowResult(status="completed", chunks=(...), artifacts={"draft_path": Path("manuscript/chapter-...md")}, metrics={"retry_count": 0})` (still template-ish content in chunks, but with the new contract).

- [x] 1.6 Update `src/writer/workflows/review_chapter.py::stub` to return `WorkflowResult(status="pending", chunks=("[workflow] review_chapter 未迁移",), metrics={"todo": "implement in PR3"})` so the deprecation branch is exercised.

- [x] 1.7 Add `case "workflow_completed"` to the `match Done.reason` in `src/writer/cli/main.py::_run_engine` (mirror the `tool_completed` rendering: print `artifacts` keys + `metrics` table). Keep `case "workflow_pending"` for PR1 (deprecation period).

- [x] 1.8 Update existing `PlainDeps` / Protocol stubs in `tests/test_engine_session.py`, `tests/test_engine_deps.py`, and any other files that hand-write `run_workflow(self, name, ctx) -> Iterable[str]` — change the return type and return a `WorkflowResult`. Grep target: `def run_workflow`. Expected ~3-5 stub updates.

- [x] 1.9 Create `tests/test_workflow_result.py` with tests for: frozen-ness, status Literal validation, JSON-serializable via `dataclasses.asdict`, all 3 status branches. ≥ 8 test cases.

- [x] 1.10 Run `uv run pytest`, `uv run ruff check src tests`, `uv run mypy src/writer` — all green. Baseline 366 tests + new tests pass.

## 2. PR2 — write_chapter real generation + persistence

- [x] 2.1 Create `src/writer/llm/prose.py` with:
  - `LLMProseError(ValueError)` exception
  - `LLMProseClient` Protocol (`@runtime_checkable`) with `name: str` attribute and `def generate_text(self, *, system: str, user: str) -> str` method
  - `RealProseClient(llm: BaseChatModel)` with `name = "real"`. `generate_text` calls `llm.invoke([SystemMessage(system), HumanMessage(user)])` and coerces content to `str` using the same logic as `writer.llm.structured._message_content_to_text`
  - `DeterministicProseClient(prep_context_fn: Callable[..., Any] = prep_context)` with `name = "deterministic"`. `generate_text` assembles structured prose (≥ 200 chars, contains chapter heading + 2 body paragraphs + end hook) from the prep_context blocks + the user message. No LLM call.

- [x] 2.2 Re-export `LLMProseClient` / `RealProseClient` / `DeterministicProseClient` / `LLMProseError` from `src/writer/llm/__init__.py`.

- [x] 2.3 Add `prose_client: LLMProseClient` field to `EngineDeps` Protocol in `src/writer/engine/deps.py`. Update the default `EngineDeps` dataclass impl. Update `production_deps(genre, project_root, settings)` to wire the prose client: `RealProseClient(get_llm(settings))` when `settings.has_api_key`, else `DeterministicProseClient(prep_context)`. **Always** set (never `None` — different from `tool_loop`).

- [x] 2.4 Update existing `PlainDeps` stubs in `tests/` to include `prose_client = <deterministic fake>` (grep `def run_workflow` is not enough; also grep `PlainDeps` and similar Protocol-stub class names).

- [x] 2.5 Create `src/writer/project/chapter_summaries.py` with:
  - `def append_summary(project_root: Path, chapter_id: str, summary: str, *, atomic: bool = True) -> Path`
  - Reads existing `chapter_summaries.json` if present; if missing, initializes with `{"chapters": []}`
  - Appends `{"chapter_id": chapter_id, "summary": summary, "written_at": <iso>}`
  - Atomic write: `tempfile.NamedTemporaryFile(dir=project_root, suffix=".json", delete=False)` + write + `os.replace`
  - Returns the path to the file
  - Raises `ValueError` if `project_root` doesn't contain `AGENT.md`
  - Add to `src/writer/project/__init__.py` re-exports

- [x] 2.6 Create `src/writer/workflows/params.py` with:
  - `@dataclass(frozen=True) class WriteChapterArgs` with fields `chapter_id: str`, `requirements: tuple[str, ...]`, `rewrite: bool`
  - `@dataclass(frozen=True) class ReviewChapterArgs` with fields `target: str`, `focus: tuple[str, ...]`
  - `def extract_write_chapter_args(user_input: str) -> WriteChapterArgs` — strips `/创作`, splits on whitespace, `rewrite=True` if `"回流"` or `"重写"` in user_input
  - `def extract_review_chapter_args(user_input: str) -> ReviewChapterArgs` — strips `/审核`, splits on whitespace

- [x] 2.7 Rewrite `src/writer/workflows/write_chapter.py`:
  - Define `WriterState` extended with `metrics: dict[str, Any]`, `artifacts: dict[str, Any]`, `prose_client_name: str`
  - Build 5-node graph: `prep_context → plan_chapter → draft_chapter → proofread → review_gate`, with conditional edge `review_gate → draft_chapter | persist_outputs`
  - `draft_chapter` calls `deps.prose_client.generate_text(system=<prompt>, user=<task>)` and stores result in `state["draft"]`
  - `review_gate`:
    - Calls `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, status="active")`
    - If `state["prose_client_name"] == "deterministic"`: returns `ReviewVerdict(pass=True, score=8, concerns=[])`
    - Else: calls `invoke_structured_json(ReviewVerdict, ...)` with prompt containing draft + active foreshadows
    - Threshold: pass iff `verdict.score >= 7`
  - `persist_outputs`:
    - Writes `manuscript/chapter-<id>.md` via `Path.write_text` + atomic helper (or `safe_write_file` if its whitelist allows it — verify in design)
    - Calls `append_summary(project_root, chapter_id, summary_text)` where `summary_text` is a deterministic one-paragraph excerpt from the draft
    - Returns `WorkflowResult(status="completed", chunks=(...), artifacts={"draft_path": ..., "summaries_path": ...}, metrics={"score": int, "retry_count": int})`
  - `run()` function: extract args via `extract_write_chapter_args`, build graph, invoke, return `WorkflowResult`

- [x] 2.8 Create `tests/test_prose_llm.py` with tests for: `RealProseClient.invoke` shape, `DeterministicProseClient` ≥ 200 chars + no "正文占位", `LLMProseError` on bad content, `isinstance` Protocol check, `production_deps` selection by `has_api_key`. ≥ 8 test cases.

- [x] 2.9 Create `tests/test_workflow_chapter_summaries.py` with tests for: missing-file creation, existing-file preservation, atomicity (assert `os.replace` use), project-root validation, isolated test fixture (no `manuscript/` side effect). ≥ 6 test cases.

- [x] 2.10 Create `tests/test_workflows_params.py` with tests for: `extract_write_chapter_args` no-args / with chapter_id / with requirements / with rewrite flag; `extract_review_chapter_args` no-args / with target / with focus. ≥ 6 test cases.

- [x] 2.11 Create `tests/test_workflows_write_chapter.py` with tests for: happy-path 5-node traversal (assert trace order), retry loop on review_gate failure, max_retries cap, `persist_outputs` writing both files, `WorkflowResult` shape, `DeterministicProseClient` integration. ≥ 8 test cases. Use `tmp_path` fixture + a stub `EngineDeps` with recording fake `LLMProseClient` + `ToolRegistry`.

- [x] 2.12 Update `tests/test_engine.py` and `tests/test_context.py` — remove any test that asserts the literal "正文占位" string (grep first to confirm what exists; only `src/writer/workflows/write_chapter.py:118` was found, but downstream tests may transitively reference it via fixture data).

- [x] 2.13 Run `uv run pytest`, `uv run ruff check src tests`, `uv run mypy src/writer` — baseline 366 + PR1 tests + PR2 tests all green. Total expected ~390+ tests.

## 3. PR3 — review_chapter multi-perspective + workflow_pending removal

- [x] 3.1 Add Pydantic models to `src/writer/workflows/types.py`:
  - `class ConcernVerdict(BaseModel)` with `score: int` (0-10, `Field(ge=0, le=10)`), `pass_: bool = Field(alias="pass")`, `findings: list[str]`
  - `class MultiConcernReview(BaseModel)` with `continuity: ConcernVerdict`, `pacing: ConcernVerdict`, `prose: ConcernVerdict`, `total_score: int`, `summary: str`
  - `class ReviewVerdict(BaseModel)` with `pass: bool`, `score: int`, `concerns: list[str]` (for write_chapter's review_gate — already specified in writing-pipeline spec)

- [x] 3.2 Rewrite `src/writer/workflows/review_chapter.py`:
  - Define `ReviewerState` TypedDict
  - Build 5-node graph: `load_target_chapter → prep_review_context → aggregate_reviews → decision_gate → persist_review_report`
  - `load_target_chapter`: reads `manuscript/chapter-<id>.md` (use `extract_review_chapter_args` to get target); if missing, return `WorkflowResult(status="failed", metrics={"error": "chapter_not_found"})`
  - `prep_review_context`: calls `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, status="active")` to get active foreshadow IDs; passes them into the review prompt
  - `aggregate_reviews`: ONE call to `invoke_structured_json(MultiConcernReview, ...)` with prompt containing the draft + active foreshadows; stores result in state
  - `decision_gate`: computes decision from `total_score` and per-concern pass flags:
    - `total_score >= 8` AND all concerns pass → `"pass"`
    - `total_score >= 6` → `"tweak"`
    - `total_score < 6` OR any concern score < 4 → `"needs_rewrite"`
  - `persist_review_report`: writes `manuscript/reviews/chapter-<id>-<iso-timestamp>.json` (e.g., `chapter-1.3-20260709T123456Z.json`); returns `WorkflowResult(status=("completed" if decision != "needs_rewrite" else "pending"), artifacts={"review_path": Path(...)}, metrics={"decision": str, "total_score": int, "concerns": {...}})`
  - Replace `stub` with `run` (no more alias)

- [x] 3.3 Update `src/writer/workflows/__init__.py` to import the new `run` (not `stub`) into `WORKFLOWS["review_chapter"]`. Re-export `MultiConcernReview`, `ConcernVerdict`, `ReviewVerdict`.

- [x] 3.4 Create `tests/test_workflows_review_chapter.py` with tests for:
  - `load_target_chapter` missing-file → `WorkflowResult(status="failed")`
  - `aggregate_reviews` single LLM call (use recording fake that returns a known `MultiConcernReview`)
  - `decision_gate` mapping (test all 3 branches: pass / tweak / needs_rewrite)
  - Continuity findings reference foreshadow IDs (asserted in persisted JSON)
  - `persist_review_report` writes the right file and `artifacts["review_path"]` matches
  - ≥ 8 test cases

- [x] 3.5 Remove `"workflow_pending"` from the `DoneReason` Literal in `src/writer/engine/events.py`. Update `engine._run_workflow` to drop the deprecation branch and the pending `Done` emission. Update `cli/main.py` to drop the `case "workflow_pending"` rendering.

- [x] 3.6 Update `tests/test_engine.py` and any other tests asserting `Done(reason="workflow_pending", ...)` — replace with the appropriate `workflow_completed` / `aborted` assertion. Grep target: `workflow_pending`. Expected ~3-5 test updates.

- [x] 3.7 Run `uv run pytest`, `uv run ruff check src tests`, `uv run mypy src/writer` — all green. Total expected ~410+ tests. E2E sanity check: `printf "/init test\n/init --brief 一个短篇\n/创作 1.1\n/审核 1.1\n" | .venv/bin/writer` should produce real prose + a review report, ending in `Done(reason="workflow_completed")` for both workflows.

- [x] 3.8 Sync delta specs to main `openspec/specs/`. Run `openspec sync-specs --change real-writing-pipeline` to materialize the new main specs (`workflow-result`, `prose-llm`, `writing-pipeline`) and the engine-loop / writer-tools deltas into `openspec/specs/`. Verify with `openspec validate --strict`.

- [x] 3.9 Run `openspec validate --strict --change real-writing-pipeline` to confirm the change is still valid for archive. Then archive via `/opsx:archive real-writing-pipeline`.
