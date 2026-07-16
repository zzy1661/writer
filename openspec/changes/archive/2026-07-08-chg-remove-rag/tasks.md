## 1. New foreshadow-ledger module

- [x] 1.1 Create `src/writer/tools/builtin/foreshadow_ledger.py` with `load_ledger(project_root: Path) -> list[dict]` and `query_ledger(entries, *, id, tags, status, chapter_range, keyword) -> list[dict]`. Use `yaml.safe_load` (PyYAML already in `pyproject.toml:30`). Return empty list on file-missing; return `[]` with a sentinel (e.g. raise `ForeshadowLedgerSchemaError`) on schema-invalid file.
- [x] 1.2 Define `ForeshadowLedgerSchemaError(Exception)` in the same module. The exception is **not** raised out of the tool — it's caught inside `ForeshadowSearch.run` to produce a friendly `ToolResult`.

## 2. Replace ForeshadowQuery with ForeshadowSearch

- [x] 2.1 Rewrite `src/writer/tools/builtin/foreshadow_tools.py`: replace `ForeshadowQuery` with `ForeshadowSearch` whose `run()` signature matches `specs/foreshadow-ledger/spec.md` Requirement: ForeshadowSearch tool signature (id / tags / status / chapter_range / keyword). All keyword-only.
- [x] 2.2 Implement the "missing file → 暂无伏笔" path and "schema-invalid file → friendly error" path. Use `runtime.project_root` directly (no `safe_path()` — the tool is path-free).
- [x] 2.3 Implement the "project_root is None" path returning `ToolResult(metadata={"error": "no_project_root"})`.
- [x] 2.4 Update `src/writer/tools/builtin/__init__.py` to export `ForeshadowSearch` (replace `ForeshadowQuery`).

## 3. Rewrite canon block

- [x] 3.1 Rewrite `src/writer/context.py::_build_canon_block` to remove the `from writer.rag import ProjectRagIndex` block (L124) and the `ProjectRagIndex(...).query(...)` call (L132-135). New composition:
  - read `outline/*.md` in full (whitelist of small files, already in scope)
  - read `characters/*.md` in full
  - read `manuscript/chapter_summaries.json` and slice by `chapter_id` + 前后 N=2 章
  - read the most recent `manuscript/chapter-XXX.md` in full (the "上一章" anchor)
- [x] 3.2 Update `ContextPack.token_audit` keys if new layers are added (e.g. `last_chapter_text`). Keep all existing keys (`system_block` / `canon_block` / `history_block` / `task_block` / `total` / `budget`) intact for downstream consumers.

## 4. Strip RAG fallback from ProjectSearch

- [x] 4.1 In `src/writer/tools/builtin/analysis_tools.py`, remove L14 `from writer.rag import ProjectRagIndex, format_hits`. Remove L100-117 (the "truncate and return early" + RAG fallback branches). Simplify `run()` so it returns the line-level grep result directly (no fallback, no `rag_matched` field).
- [x] 4.2 Update the tool's `description` to drop the "RAG 召回" mention — keep it as a pure Grep analog.

## 5. Delete rag.py

- [x] 5.1 Delete `src/writer/rag.py` entirely.
- [x] 5.2 Run `rg "writer\.rag|from writer import rag|import writer.rag" src/ tests/` and confirm zero hits. If hits remain, fix them in their own files (most likely: a test imports the deleted module).

## 6. Update pyproject.toml dependencies

- [x] 6.1 Remove `"faiss-cpu>=1.8.0"` from `pyproject.toml:28`.
- [x] 6.2 Audit `langchain-community>=0.3.0` (L20) usage: `rg "langchain_community" src/ tests/`. If only `rag.py` references it (now deleted), also remove the dependency. Otherwise leave it.
- [x] 6.3 Run `uv sync --all-extras` to update `uv.lock`.

## 7. Update router and engine spec references

- [x] 7.1 In `src/writer/routing/intent_router.py` (or wherever the rule-based router's `foreshadow_query` literal lives), replace `foreshadow_query` → `foreshadow_search` and update the example `arguments` shape from `{"query": "..."}` to `{"id": "..."}` (or whichever minimal shape the rule emits).
- [x] 7.2 Update any router test fixture that hard-codes `foreshadow_query` / `{"query": "F003"}` to the new tool name and arg shape. Look in `tests/test_routing*.py`, `tests/test_intent*.py`, etc.
- [x] 7.3 In `src/writer/engine/loop.py`, confirm the `call_tool` dispatch path still works (it dispatches by `tool_name` string; no change needed unless there's a hard-coded `foreshadow_query` reference). If present, update.

## 8. Test rewrites

- [x] 8.1 Rename `tests/test_context_rag.py` → `tests/test_context.py`. Update imports: remove `from writer.rag import ProjectRagIndex, collect_project_documents`. Update assertions: canon block should now contain outline full text + character full text + chapter summary excerpts.
- [x] 8.2 Add `tests/test_foreshadow_ledger.py` covering all scenarios in `specs/foreshadow-ledger/spec.md`:
  - missing file → "暂无伏笔" message
  - empty list → "暂无伏笔" message
  - schema-invalid file → friendly error result, no raise
  - lookup by id (single match)
  - filter by status=laid (excludes paid)
  - filter by status=paid
  - filter by status=all
  - filter by tag (any-of)
  - filter by chapter_range
  - keyword substring match (id / tags / notes)
  - multiple filters AND-combine
  - project_root None → `metadata.error="no_project_root"`
- [x] 8.3 Add or update `tests/test_routing_intent.py` (or equivalent) to use the new `foreshadow_search` tool name and `{id: "F003"}` arg shape per `specs/intent-routing/spec.md`.
- [x] 8.4 Update `tests/test_engine_loop.py` scenarios that reference `foreshadow_query` to use `foreshadow_search` per `specs/engine-loop/spec.md`.

## 9. OpenSpec validation

- [x] 9.1 Run `openspec validate chg-remove-rag --strict` and resolve all warnings/errors. Expected clean pass.
- [x] 9.2 Run `openspec show chg-remove-rag --json --type requirement` to confirm delta spec operations (MODIFIED) for `intent-routing` and `engine-loop` are recorded, and ADDED for `foreshadow-ledger`.

## 10. Final quality gate

- [x] 10.1 Run `uv run ruff check src tests` — zero violations.
- [x] 10.2 Run `uv run mypy src/writer` — zero errors.
- [x] 10.3 Run `uv run pytest` — all tests pass (target: 277+ tests; baseline 276 per `MEMORY.md` 验证基线).
- [x] 10.4 Run e2e: `printf "/大纲 一个穿越到唐朝的程序员\n" | .venv/bin/writer` — observe the same 5 `Done` branches as before (the only behavioral change: `foreshadow_query` is now `foreshadow_search`).
