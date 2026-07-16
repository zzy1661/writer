# Capability: writer-tools (delta for real-writing-pipeline)

## Purpose

This delta adds an atomic write helper for `chapter_summaries.json` so the `write_chapter` workflow can persist per-chapter summaries without corrupting the file under concurrent reads.

## ADDED Requirements

### Requirement: chapter_summaries.append_summary writes atomically

The system SHALL provide `writer.project.chapter_summaries.append_summary(project_root: Path, chapter_id: str, summary: str, *, atomic: bool = True) -> Path` that appends a new entry to the project's `chapter_summaries.json` and returns the path to the updated file. When `atomic=True` (default), the write MUST use `tempfile.NamedTemporaryFile(dir=parent) + os.replace` so concurrent readers never observe a partial file.

#### Scenario: append_summary creates file when missing
- **WHEN** `append_summary(project_root, "1.1", "first summary")` is called on a project where `chapter_summaries.json` does NOT exist
- **THEN** the file MUST be created at `<project_root>/chapter_summaries.json`
- **AND** the file MUST contain a JSON object with the new chapter entry (shape TBD in design.md; minimum required keys: `chapter_id` and `summary`)

#### Scenario: append_summary preserves existing entries
- **WHEN** `append_summary` is called on a project where `chapter_summaries.json` already contains entries for chapters 1.1 and 1.2
- **THEN** the updated file MUST contain entries for 1.1, 1.2, AND the new chapter (no overwrite, no key loss)

#### Scenario: append_summary uses os.replace for atomicity
- **WHEN** `append_summary` runs with `atomic=True`
- **THEN** the implementation MUST use `tempfile.NamedTemporaryFile` in the same directory followed by `os.replace` (assertable by inspecting the function source or by a side-effect-recording test)
- **AND** no `.tmp.*` file MUST remain after the call returns

#### Scenario: append_summary is project-scoped
- **WHEN** `append_summary(project_root, "1.1", "x")` is called
- **THEN** the file MUST be written under `project_root`, never under the caller's CWD or a different root
- **AND** if `project_root` does not contain a `writer` project marker (e.g., `AGENT.md`), the function MUST raise `ValueError` with a message mentioning the missing project root

### Requirement: chapter_summaries.append_summary is independently testable

The `append_summary` function SHALL be importable from `writer.project.chapter_summaries` and SHALL NOT require an LLM, a ToolRuntime, or any other engine infrastructure. Tests MUST be able to call it with a `tmp_path` fixture alone.

#### Scenario: append_summary works in test isolation
- **WHEN** a test creates a `tmp_path` directory and calls `append_summary(tmp_path, "1.1", "x")`
- **THEN** the file MUST be created at `tmp_path/chapter_summaries.json`
- **AND** no other filesystem side effects MUST occur (no `manuscript/` dir created, no checkpoints, etc.)
