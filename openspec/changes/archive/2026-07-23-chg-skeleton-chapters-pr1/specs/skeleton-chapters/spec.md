# skeleton-chapters Specification (delta)

> **PR1 范围说明**：本 spec 描述 `/骨架` shipped workflow 的全部能力。PR1 仅落地 full / volume / range 三态 + deterministic raise + 直接落盘；`view` / `continue` / `rewrite` 在 PR1.5 / PR2 单独 change 中实装，对应 Requirements 在本 spec 中以 `PR1` / `PR1.5` / `PR2` 标注。spec 一次性写齐是为了让 main specs sync 时一次性合并。

## Purpose

定义 `/骨架` 命令对应的 LangGraph 工作流 `skeleton_chapters` 的输入契约、节点职责、产物结构、`WorkflowResult` 3 状态映射、以及与现有 Runner / ProjectState / ProseClient 的集成边界。是 `/大纲` 与 `/创作` 之间的中间粒度批量生成工具。

## ADDED Requirements

### Requirement: skeleton_chapters is a registered workflow

The system SHALL register `skeleton_chapters` as a key in `writer.workflows.WORKFLOWS` (per `workflows/__init__.py:26-29`), pointing to `writer.workflows.skeleton_chapters.run(ctx: RunnerContext, deps: RunnerDeps) -> WorkflowResult`.

#### Scenario: skeleton_chapters appears in WORKFLOWS
- **WHEN** `from writer.workflows import WORKFLOWS` is executed after PR1 applies
- **THEN** `"skeleton_chapters"` MUST be a key in `WORKFLOWS`
- **AND** the callable MUST accept `(ctx: RunnerContext, deps: RunnerDeps)` and return `WorkflowResult`

#### Scenario: production_deps exposes skeleton_chapters
- **WHEN** `production_deps()` is called (per `runner/deps.py::production_deps`)
- **THEN** `deps._workflows` MUST include `"skeleton_chapters"`
- **AND** `deps.run_workflow("skeleton_chapters", ctx)` MUST dispatch to `skeleton_chapters.run`

### Requirement: SkeletonArgs dataclass captures parsed command input

The system SHALL define `SkeletonArgs` (per `workflows/params.py`) as a `@dataclass(frozen=True)` with fields: `mode: Literal["full", "volume", "range"]`, `volume: str = ""`, `start: str = ""`, `end: str = ""`, `rewrite: bool = False`, `continue_: bool = False`, `view: bool = False`.

`extract_skeleton_args(user_input: str) -> SkeletonArgs` SHALL parse `/骨架` input:
- Empty after prefix strip → `SkeletonArgs(mode="full")`
- First token matches `^卷[一-十]$` → `SkeletonArgs(mode="volume", volume=<token>)`
- First token matches `^\d+\.\d+-\d+\.\d+$` → `SkeletonArgs(mode="range", start=<left>, end=<right>)`
- Other forms → `raise SkillError("无效章节范围: 应为 X.Y-X.Z 形式")`

PR1 only honors `mode` / `volume` / `start` / `end`. `rewrite` / `continue_` / `view` are accepted but ignored; their semantics land in PR1.5 / PR2.

#### Scenario: bare /骨架 parses as full mode
- **WHEN** `extract_skeleton_args("/骨架")` is called
- **THEN** the result MUST be `SkeletonArgs(mode="full", volume="", start="", end="", rewrite=False, continue_=False, view=False)`

#### Scenario: /骨架 卷一 parses as volume mode
- **WHEN** `extract_skeleton_args("/骨架 卷一")` is called
- **THEN** the result MUST be `SkeletonArgs(mode="volume", volume="卷一")`

#### Scenario: /骨架 1.1-1.20 parses as range mode
- **WHEN** `extract_skeleton_args("/骨架 1.1-1.20")` is called
- **THEN** the result MUST be `SkeletonArgs(mode="range", start="1.1", end="1.20")`

#### Scenario: single-layer range is rejected
- **WHEN** `extract_skeleton_args("/骨架 1-20")` is called
- **THEN** the function MUST raise `SkillError` whose message contains "X.Y-X.Z"

#### Scenario: cross-volume range accepted (PR2 semantic refinement)
- **WHEN** `extract_skeleton_args("/骨架 1.1-2.20")` is called
- **THEN** the result MUST be `SkeletonArgs(mode="range", start="1.1", end="2.20")`
- **AND** PR1 workflow treats this as "subset of start..end chapters"; PR2 refines semantics

#### Scenario: SkeletonArgs is frozen
- **WHEN** a caller mutates any field on the returned `SkeletonArgs`
- **THEN** the assignment MUST raise `dataclasses.FrozenInstanceError`

### Requirement: skeleton_chapters graph is a 6-node LangGraph

The system SHALL build a `StateGraph(SkeletonState)` with these nodes in order: `load_inputs → parse_toc → init_or_load_progress → generate_batch → persist_skeleton → finalize`. The graph MUST be compiled with a checkpointer (SQLite if `project_root` is set, otherwise `MemorySaver`, per `write_chapter.py::_build_checkpointer:604-622`).

PR1 `init_or_load_progress` SHALL only write a fresh `骨架/进度.json` with `status="running", completed=[], current=null`. Reading existing progress (continue semantics) lands in PR2.

#### Scenario: happy path traverses all 6 nodes once
- **WHEN** `/骨架` runs against an S4 project with 2 chapters in TOC
- **THEN** the graph MUST execute `load_inputs → parse_toc → init_or_load_progress → generate_batch → persist_skeleton → finalize` in that order
- **AND** the `trace` field MUST include all 6 node names

#### Scenario: PR1 init_or_load_progress does not read existing progress
- **WHEN** `/骨架` runs against a project with a pre-existing `骨架/进度.json` containing `{"status": "completed", "completed": ["1.1"]}`
- **THEN** PR1 MUST overwrite the file with `{"status": "running", "completed": [], "current": null}`
- **AND** PR1 MUST regenerate all chapters (no skip logic) — continue semantics lands in PR2

### Requirement: load_inputs validates project state and inputs

The `load_inputs` node MUST:
1. Reject if `project_root` is None → set `state["error"] = "未绑定项目"`.
2. Reject if `project_state < S4` → set `state["error"] = "项目状态 < S4，请先执行 /目录"`.
3. Reject if `大纲/大纲.md` missing → set `state["error"] = "缺少大纲/大纲.md，请先执行 /大纲"`.
4. Reject if `大纲/章节目录.md` missing → set `state["error"] = "缺少大纲/章节目录.md，请先执行 /目录"`.
5. Read AGENT.md via `state.py::read_genre_from_agent` + `read_architecture_method_from_agent` and attach to `state["canon_meta"]`.

On `error` set, downstream nodes MUST short-circuit to `finalize` with `WorkflowResult(status="failed")`.

#### Scenario: load_inputs rejects S3 project
- **WHEN** `/骨架` runs against an S3 project (大纲 done, TOC missing)
- **THEN** the resulting `WorkflowResult.status` MUST be `"failed"`
- **AND** `metrics["error"]` MUST contain "请先执行 /目录"
- **AND** NO file under `骨架/` MUST be created

#### Scenario: load_inputs rejects no project root
- **WHEN** `RunnerContext.project_root is None`
- **THEN** the resulting `WorkflowResult.status` MUST be `"failed"`
- **AND** `metrics["error"]` MUST contain "未绑定项目"

### Requirement: generate_batch calls prose_client once per chapter

The `generate_batch` node MUST iterate over `state["tasks"]` (filtered by `SkeletonArgs.mode` / `volume` / `start` / `end`) and call `_call_generate_open_close(deps.prose_client, ...)` per chapter. PR1 serial iteration (per `TODO/骨架命令.md` §10); `prev_closing` is passed to the next chapter's prompt, truncated to 500 chars.

Each `prose_client.generate_text` call MUST produce `## 开头` + `## 结尾` sections. Parsing failures retry once, then raise `RuntimeError("skeleton_chapter 单章生成失败")`.

#### Scenario: serial iteration with prev_closing threading
- **WHEN** `generate_batch` runs against 3 chapters
- **THEN** chapter 2's prompt MUST include chapter 1's `closing_text` (substring check)
- **AND** chapter 3's prompt MUST include chapter 2's `closing_text`
- **AND** chapter 1's prompt MUST NOT include any `prev_closing` (first chapter convention)

#### Scenario: prose_client called once per chapter
- **WHEN** a recording `RealProseClient` is wired and the graph runs against 2 chapters
- **THEN** the recording MUST show exactly 2 `generate_text` calls

### Requirement: deterministic mode raises immediately

The `_call_generate_open_close` helper MUST raise `RuntimeError("skeleton_chapter 需要真实 LLM；请设置 WRITER_API_KEY 环境变量后重启")` when `prose_client is None` or `prose_client.name == "deterministic"`. This mirrors the `write_chapter._call_plan_chapter:428-432` strict-raise contract (per MEMORY 2026-07-14 decision).

#### Scenario: deterministic client raises RuntimeError
- **WHEN** `_call_generate_open_close(prose_client=DeterministicProseClient(), ...)` is called
- **THEN** the function MUST raise `RuntimeError`
- **AND** the error message MUST contain "WRITER_API_KEY"

#### Scenario: real client proceeds normally
- **WHEN** `_call_generate_open_close(prose_client=RealProseClient(...), ...)` is called
- **THEN** the function MUST return `(opening_text, closing_text)` without raising

### Requirement: persist_skeleton writes directly via Path.write_text

The `persist_skeleton` node MUST write each chapter file using direct `Path.write_text`, mirroring `write_chapter._persist_outputs_node:322-326`. The path pattern is `project_root / "骨架" / <volume> / f"第{seq:03d}章.md"`. Files MUST NOT go through `safe_write_file` tool (PR1 does not extend `DEFAULT_WRITE_WHITELIST`).

#### Scenario: chapter files land under 骨架/<volume>/
- **WHEN** `persist_skeleton` runs against chapter_id=1.1 in 卷一
- **THEN** `<project_root>/骨架/卷一/第001章.md` MUST exist after completion
- **AND** the file content MUST contain `## 开头` and `## 结尾` markdown sections

#### Scenario: no safe_write_file tool invocation
- **WHEN** the full graph runs with a spy `ToolRegistry`
- **THEN** the spy MUST record ZERO `safe_write_file` calls
- **AND** the spy MUST record ZERO `safe_edit_file` calls
- **AND** `DEFAULT_WRITE_WHITELIST` MUST NOT contain "骨架" after PR1 (verified by reading `tools/runtime.py`)

### Requirement: finalize writes 索引.md and returns WorkflowResult

The `finalize` node MUST:
1. Write `<project_root>/骨架/索引.md` with one-line per chapter (chapter_id + opening first 30 chars + closing first 30 chars).
2. Construct `WorkflowResult`:
   - On success: `status="completed"`, `artifacts={"skeleton_root": Path, "index_path": Path}`, `metrics={"chapter_count": int, "mode": str, "volume": str, "rewrite": 0, "resumed": 0}`.
   - On exception mid-batch: `status="failed"`, `artifacts={"progress_path": Path}`, `metrics={"partial_chapters": int, "mode": str, "volume": str}` — and `progress_path` JSON has `{"status": "failed", "completed": [...], "current": "<last_in_progress>"}`.

#### Scenario: completed workflow carries artifacts
- **WHEN** the graph runs against 3 chapters without error
- **THEN** the returned `WorkflowResult.status` MUST be `"completed"`
- **AND** `metrics["chapter_count"]` MUST be 3
- **AND** `metrics["mode"]` MUST be `"full"`
- **AND** `artifacts["index_path"]` MUST point to an existing `<project_root>/骨架/索引.md`

#### Scenario: partial failure uses status=failed with partial_chapters
- **WHEN** the LLM raises on chapter 2 of 3 (chapter 1 already written)
- **THEN** the returned `WorkflowResult.status` MUST be `"failed"`
- **AND** `metrics["partial_chapters"]` MUST be 1
- **AND** `artifacts["progress_path"]` MUST point to a JSON file containing `"status": "failed"` and `"completed": ["1.1"]`

#### Scenario: pending status is never used by skeleton_chapters
- **WHEN** any code path in `skeleton_chapters.run` would naturally produce a partial-completion signal
- **THEN** it MUST NOT set `WorkflowResult.status = "pending"`
- **AND** partial completion MUST be expressed via `status="failed"` + `metrics["partial_chapters"]` instead
- **BECAUSE** `runner/runner.py::_run_workflow:392-407` reserves `pending` for the `needs_rewrite` signal exclusively (per `runner/events.py:24`)

### Requirement: IntentRouter routes /骨架 to skeleton_chapters workflow

`RuleBasedIntentRouter.route("/骨架 ...")` MUST return `AgentAction(action_type="start_workflow", command="/骨架", role="story_agent", workflow="skeleton_chapters", arguments={"raw": text})`. The branch MUST be placed adjacent to `/创作` / `/审核` branches (per `intent_router.py:101-116`).

The fallback `answer_directly` text (per `intent_router.py:130-136`) MUST include `/骨架` in the command list.

`LlmIntentRouter` MUST NOT require changes — `CompositeRouter` primary (rule) catches any `/`-prefixed input (per `CompositeRouter` + `looks_like_command` at `intent_router.py:148-153`).

#### Scenario: /骨架 routes to skeleton_chapters
- **WHEN** `RuleBasedIntentRouter().route("/骨架 卷二", _project_state="S4")` is called
- **THEN** the returned `AgentAction.workflow` MUST be `"skeleton_chapters"`
- **AND** `action_type` MUST be `"start_workflow"`

#### Scenario: fallback answer text includes /骨架
- **WHEN** `RuleBasedIntentRouter().route("random prose", _project_state="S4")` is called
- **THEN** the returned `AgentAction.answer` MUST contain "/骨架"

### Requirement: chapter prompt consumes AGENT.md metadata

The `_build_chapter_prompt` helper MUST read AGENT.md `题材:` and `架构方法:` lines via `state.py::read_genre_from_agent` and `read_architecture_method_from_agent` (per MEMORY 2026-07-16 decision). The system prompt MUST contain both values as substrings.

#### Scenario: prompt includes genre from AGENT.md
- **WHEN** the graph runs against a project with `题材: 玄幻` in AGENT.md
- **THEN** the captured `system` message of each `prose_client.generate_text` call MUST contain "玄幻"

#### Scenario: prompt includes architecture method from AGENT.md
- **WHEN** the graph runs against a project with `架构方法: 雪花法` in AGENT.md
- **THEN** the captured `system` message MUST contain "雪花法"

### Requirement: chapter file template uses 1.1-style chapter_id

Each generated `<project_root>/骨架/<volume>/第{seq:03d}章.md` MUST include frontmatter-like metadata (`chapter_id`, `volume`, `目录摘要`) plus `## 开头` / `## 结尾` / `## 衔接备注` sections. `OPEN_MAX_CHARS = 400` and `CLOSE_MAX_CHARS = 300` are module-level constants in `writer.workflows.skeleton_chapters`. Per-genre tuning lands in PR2+.

#### Scenario: chapter file has expected sections
- **WHEN** `persist_skeleton` writes chapter 1.1
- **THEN** the file MUST contain lines `# 第 1.1 章 ·`, `## 元信息`, `chapter_id: 1.1`, `volume: 卷一`, `## 开头`, `## 结尾`, `## 衔接备注`
- **AND** the `## 开头` section MUST be ≤ 400 chars (excluding markdown structure)
- **AND** the `## 结尾` section MUST be ≤ 300 chars

### Requirement: skeleton_chapters does not modify Runner or WorkflowResult

The system MUST NOT modify `Runner` (in `runner/runner.py`), `RunnerDeps` Protocol, `WorkflowResult` dataclass, or `_run_workflow` dispatch helper as part of PR1. All existing Runner surface area already supports the 3-status mapping that skeleton_chapters requires.

#### Scenario: no changes to runner package
- **WHEN** PR1 applies
- **THEN** `git diff src/writer/runner/` MUST be empty
- **AND** `git diff src/writer/workflows/types.py` MUST be empty
- **AND** `git diff src/writer/runner/deps.py` MUST be empty
- **AND** `git diff src/writer/tools/runtime.py` MUST be empty