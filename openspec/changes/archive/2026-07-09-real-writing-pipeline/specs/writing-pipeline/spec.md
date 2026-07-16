# Capability: writing-pipeline

## Purpose

The end-to-end writing pipeline: `write_chapter` (drafting) and `review_chapter` (multi-perspective review) as LangGraph state machines, with deterministic / LLM-driven node implementations, atomic persistence to `manuscript/` and `chapter_summaries.json`, and a structured `WorkflowResult` return contract (see `workflow-result` spec).

## ADDED Requirements

### Requirement: write_chapter builds a 5-node LangGraph

The `write_chapter` workflow SHALL build a `StateGraph(WriterState)` with the following nodes in order: `prep_context` → `plan_chapter` → `draft_chapter` → `proofread` → `review_gate`, with a conditional edge from `review_gate` to either `draft_chapter` (rewrite) or `persist_outputs` (success). `persist_outputs` is a terminal node that writes files and updates state.

The graph MUST be compiled with the existing SQLite/Memory checkpointer pattern from the current MVP (`src/writer/workflows/write_chapter.py::_build_checkpointer`).

#### Scenario: happy path traverses all 5 nodes once
- **WHEN** `/创作 1.3` runs against a project with no prior chapter 1.3
- **THEN** the graph MUST execute `prep_context → plan_chapter → draft_chapter → proofread → review_gate → persist_outputs` in that order
- **AND** the final `trace` field MUST include all 5 node names

#### Scenario: review gate failure triggers a rewrite
- **WHEN** the `review_gate` returns `{"needs_rewrite": True, "retry_count": 0, "max_retries": 2}`
- **THEN** the graph MUST route back to `draft_chapter` and increment `retry_count`
- **AND** the second `draft_chapter` call MUST receive the updated `retry_count` in state

#### Scenario: max_retries cap is honored
- **WHEN** `retry_count` has already reached `max_retries` and `review_gate` still wants a rewrite
- **THEN** the graph MUST route to `persist_outputs` instead of looping (best-effort, accept current draft)
- **AND** `metrics["review_loop_exhausted"]` MUST be `True`

### Requirement: draft_chapter uses LLMProseClient

The `draft_chapter` node MUST call `deps.prose_client.generate_text(system=<canon+history prompt>, user=<task+chapter_id prompt>)` and store the returned string in `state["draft"]`. When the prose client is `DeterministicProseClient`, the returned draft MUST be at least 200 characters of structured prose (not a single-line placeholder).

#### Scenario: draft_chapter with RealProseClient records the LLM call
- **WHEN** a recording `RealProseClient` is wired and `draft_chapter` runs
- **THEN** the recording MUST show exactly one `generate_text` call
- **AND** the `system` argument MUST contain the chapter's `canon_block` and `history_block` (substring check)

#### Scenario: draft_chapter with DeterministicProseClient never invokes LLM
- **WHEN** a `DeterministicProseClient` is wired and `draft_chapter` runs
- **THEN** the resulting `state["draft"]` MUST be ≥ 200 characters
- **AND** the draft MUST contain a chapter heading line and at least one body paragraph
- **AND** the draft MUST NOT contain the literal string "正文占位"

### Requirement: review_gate threshold is fixed at 7

The `review_gate` node MUST evaluate the draft against the active foreshadows and produce a `ReviewVerdict` Pydantic model with fields `pass: bool`, `score: int` (0-10), `concerns: list[str]`. The pass rule is:

- When `deps.prose_client.name == "deterministic"`: auto-pass with `score=8`, `concerns=[]`.
- When `deps.prose_client.name == "real"`: invoke `invoke_structured_json(ReviewVerdict, ...)` with a prompt that includes the draft + active foreshadows (via `foreshadow_search(status="active")`); pass iff `verdict.score >= 7`.

The threshold value (7) is fixed in PR2; tuning is deferred to a follow-up change.

#### Scenario: deterministic mode auto-passes at score 8
- **WHEN** `review_gate` runs with a `DeterministicProseClient`
- **THEN** the produced `ReviewVerdict` MUST have `pass=True` and `score=8`
- **AND** no LLM call MUST be made for the verdict

#### Scenario: real mode LLM verdict below threshold triggers rewrite
- **WHEN** `review_gate` runs with a `RealProseClient` whose stub returns `ReviewVerdict(pass=False, score=5, concerns=["continuity gap on F003"])`
- **THEN** the resulting `state["review"]` MUST have `needs_rewrite=True`
- **AND** the graph MUST route back to `draft_chapter`

#### Scenario: real mode LLM verdict at or above threshold passes
- **WHEN** `review_gate` runs with a `RealProseClient` whose stub returns `ReviewVerdict(pass=True, score=9, concerns=[])`
- **THEN** the resulting `state["review"]` MUST have `needs_rewrite=False`
- **AND** the graph MUST route to `persist_outputs`

### Requirement: review_gate reuses foreshadow_search

`review_gate` MUST call `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, status="active")` to load the active foreshadows before producing the verdict. The active foreshadows MUST be included in the LLM prompt for real mode.

#### Scenario: review_gate loads active foreshadows before verdict
- **WHEN** a recording `ToolRegistry` is wired and `review_gate` runs
- **THEN** the registry MUST record exactly one `foreshadow_search` call with `status="active"`

### Requirement: persist_outputs writes manuscript + chapter_summaries atomically

The `persist_outputs` node MUST:

1. Write the draft to `manuscript/chapter-<chapter_id>.md` via the `safe_write_file` tool (or a direct `Path.write_text` + atomic helper, depending on what `safe_write_file` allows — final choice in `design.md`).
2. Call `writer.project.chapter_summaries.append_summary(project_root, chapter_id, summary)` where `summary` is a one-paragraph string derived from the draft.
3. Return a `WorkflowResult(status="completed", chunks=(...), artifacts={"draft_path": <Path>, "summaries_path": <Path>}, metrics={"score": int, "tokens": int, "retry_count": int})`.

#### Scenario: persist_outputs writes both files and reports paths
- **WHEN** `persist_outputs` runs with `chapter_id="1.3"` and a draft string
- **THEN** `manuscript/chapter-1.3.md` MUST exist with the draft content
- **AND** `chapter_summaries.json` MUST contain a new entry for chapter `1.3`
- **AND** the returned `WorkflowResult.artifacts` MUST include both `draft_path` and `summaries_path`

#### Scenario: append_summary is atomic
- **WHEN** `append_summary(project_root, "1.3", "summary text")` is called on a project that has a pre-existing `chapter_summaries.json`
- **THEN** the write MUST be atomic (tempfile + `os.replace`)
- **AND** the existing entries MUST be preserved (no overwrite)

### Requirement: chapter_summaries.append_summary has stable shape

`writer.project.chapter_summaries.append_summary` SHALL have signature:

```python
def append_summary(
    project_root: Path,
    chapter_id: str,
    summary: str,
    *,
    atomic: bool = True,
) -> Path
```

It MUST return the path to the updated `chapter_summaries.json`. When `atomic=True` (default), it MUST use `tempfile.NamedTemporaryFile + os.replace` so concurrent readers never observe a half-written file.

#### Scenario: append_summary on missing file creates chapter_summaries.json
- **WHEN** `append_summary(project_root, "1.1", "first chapter summary")` is called on a project without `chapter_summaries.json`
- **THEN** the file MUST be created with `{"chapters": [{"chapter_id": "1.1", "summary": "first chapter summary"}]}` (or the project's existing shape — TBD in design)

#### Scenario: append_summary preserves order
- **WHEN** `append_summary` is called three times with chapter_ids `["1.1", "1.2", "1.3"]`
- **THEN** the resulting JSON's `chapters` list MUST preserve the insertion order

### Requirement: review_chapter builds a 5-node reviewer graph

The `review_chapter` workflow SHALL build a `StateGraph(ReviewerState)` with nodes: `load_target_chapter` → `prep_review_context` → `aggregate_reviews` → `decision_gate` → `persist_review_report`. The reviewer logic is a SINGLE structured LLM call returning a `MultiConcernReview` Pydantic model with three concerns (continuity / pacing / prose) + total score. Three parallel LLM calls are deferred to a follow-up change.

`MultiConcernReview` schema (Pydantic):
- `continuity: ConcernVerdict` (where `ConcernVerdict = {score: int, findings: list[str], pass_: bool}`)
- `pacing: ConcernVerdict`
- `prose: ConcernVerdict`
- `total_score: int` (0-10, weighted average or simple average)
- `summary: str`

`decision_gate` outputs `pass | tweak | needs_rewrite`. The mapping:
- `total_score >= 8` AND all concerns pass → `pass`
- `total_score >= 6` → `tweak` (return `status=completed` with `metrics["decision"]="tweak"`)
- `total_score < 6` OR any concern fails badly → `needs_rewrite` (return `status=pending` with `metrics["decision"]="needs_rewrite"`)

#### Scenario: high score yields pass decision
- **WHEN** the LLM returns `MultiConcernReview(total_score=9, ...)` with all concerns passing
- **THEN** `decision_gate` MUST emit `metrics["decision"]="pass"`
- **AND** the returned `WorkflowResult.status` MUST be `"completed"`

#### Scenario: medium score yields tweak decision
- **WHEN** the LLM returns `MultiConcernReview(total_score=7, ...)` with all concerns passing
- **THEN** `decision_gate` MUST emit `metrics["decision"]="tweak"`
- **AND** the returned `WorkflowResult.status` MUST be `"completed"` (tweak is delivered, not a rewrite request)

#### Scenario: low score yields needs_rewrite
- **WHEN** the LLM returns `MultiConcernReview(total_score=4, ...)`
- **THEN** `decision_gate` MUST emit `metrics["decision"]="needs_rewrite"`
- **AND** the returned `WorkflowResult.status` MUST be `"pending"` (so upstream callers know to re-invoke `write_chapter`)

### Requirement: review_chapter continuity concern reuses foreshadow_search

The continuity concern's prompt MUST include the active foreshadows, fetched via `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, status="active")`. The findings MUST reference specific foreshadow IDs (e.g., `["F003 unfulfilled at chapter 1.3"]`).

#### Scenario: continuity findings reference foreshadow IDs
- **WHEN** the LLM stub returns findings containing `"F003 unfulfilled"` and `"F007 timing"` for the continuity concern
- **THEN** the persisted review report MUST include those exact strings
- **AND** the report MUST also list the active foreshadow IDs the reviewer was given (so the user can cross-check)

### Requirement: review_chapter persists report to manuscript/reviews/

The `persist_review_report` node MUST write `manuscript/reviews/chapter-<chapter_id>-<ISO-timestamp>.json` with shape:

```json
{
  "chapter_id": "1.3",
  "timestamp": "2026-07-09T12:34:56Z",
  "total_score": 7,
  "decision": "tweak",
  "concerns": {
    "continuity": {"score": 8, "pass": true, "findings": [...]},
    "pacing": {...},
    "prose": {...}
  },
  "active_foreshadows": ["F001", "F003"]
}
```

The returned `WorkflowResult.artifacts` MUST include `review_path: Path(...)`.

#### Scenario: review report is written and surfaced in artifacts
- **WHEN** `review_chapter` completes successfully on chapter 1.3
- **THEN** `manuscript/reviews/chapter-1.3-*.json` MUST exist (one file, timestamp-suffixed)
- **AND** the file's JSON MUST match the schema above
- **AND** `WorkflowResult.artifacts["review_path"]` MUST equal that file's path

### Requirement: writer.workflows.params parses /创作 and /审核

The `writer.workflows.params` module SHALL export:

- `def extract_write_chapter_args(user_input: str) -> WriteChapterArgs` where `WriteChapterArgs` is a frozen dataclass with `chapter_id: str`, `requirements: tuple[str, ...]`, `rewrite: bool`.
- `def extract_review_chapter_args(user_input: str) -> ReviewChapterArgs` where `ReviewChapterArgs` has `target: str` (chapter_id or "current"), `focus: tuple[str, ...]`.

The `rewrite` flag MUST be True iff the user input contains the substring `"回流"` or `"重写"`. Both functions MUST return a result with sensible defaults (chapter_id `"1.1"` for write, target `"current"` for review) when the input has no extra arguments.

#### Scenario: write chapter with no args defaults to 1.1
- **WHEN** `extract_write_chapter_args("/创作")` is called
- **THEN** the result MUST be `WriteChapterArgs(chapter_id="1.1", requirements=(), rewrite=False)`

#### Scenario: write chapter with chapter_id and requirements
- **WHEN** `extract_write_chapter_args("/创作 2.4 突出冲突，结尾留钩")` is called
- **THEN** the result MUST be `WriteChapterArgs(chapter_id="2.4", requirements=("突出冲突", "结尾留钩"), rewrite=False)`

#### Scenario: write chapter with rewrite flag
- **WHEN** `extract_write_chapter_args("/创作 1.3 请回流重写冲突段落")` is called
- **THEN** the result MUST have `rewrite=True`

#### Scenario: review chapter with target and focus
- **WHEN** `extract_review_chapter_args("/审核 1.3 重点看伏笔")` is called
- **THEN** the result MUST be `ReviewChapterArgs(target="1.3", focus=("重点看伏笔",))`

#### Scenario: review chapter with no args defaults to current
- **WHEN** `extract_review_chapter_args("/审核")` is called
- **THEN** the result MUST be `ReviewChapterArgs(target="current", focus=())`
