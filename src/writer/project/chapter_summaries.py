"""Atomic write helper for ``chapter_summaries.json``.

The ``write_chapter`` workflow (real-writing-pipeline PR2) appends a
per-chapter summary to the project's ``chapter_summaries.json`` after
writing the chapter draft. This helper:

* Loads the existing JSON (or initializes ``{"chapters": []}`` on a
  fresh project).
* Appends a new entry: ``{"chapter_id", "summary", "written_at"}``.
* Writes the file **atomically** (tempfile + ``os.replace``) so
  concurrent readers (e.g. the REPL's per-turn canon-block builder)
  never observe a half-written file.

The function is intentionally narrow and project-scoped: it lives in
``writer.project`` because ``chapter_summaries.json`` is a project
artifact (read by the canon block, written by the workflow). It does
NOT touch ``safe_write_file`` because the file is JSON and needs
read-modify-write semantics; the Tool layer would have to add another
mode for that one shape.

Added 2026-07-09 (real-writing-pipeline PR2).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUMMARIES_FILE = "chapter_summaries.json"


class ChapterSummariesError(ValueError):
    """Raised when the chapter_summaries helper cannot operate.

    Inherits from ``ValueError`` (same as other domain exceptions in
    this package) so the engine's ``except Exception`` arm surfaces it
    as a normal aborted turn.
    """


def _is_project_root(path: Path) -> bool:
    """Return True when ``path`` looks like a writer project root.

    The check is intentionally cheap: the project marker is
    ``AGENT.md`` (always written by :func:`writer.project.create_workspace`).
    """
    return (path / "AGENT.md").exists()


def _now_iso() -> str:
    """Return the current UTC time in ISO 8601 format with ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_existing(path: Path) -> dict[str, Any]:
    """Load the existing ``chapter_summaries.json`` if present.

    Returns a normalised ``{"chapters": [...]}`` shape. If the existing
    file uses a different shape (legacy migration case), the prior
    payload is preserved under ``"_legacy"`` so no data is lost.
    """
    if not path.exists():
        return {"chapters": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"chapters": []}
    if not isinstance(raw, dict):
        return {"chapters": []}
    if "chapters" in raw and isinstance(raw["chapters"], list):
        return raw
    # Legacy shape: store the original under ``_legacy`` and start a
    # fresh ``chapters`` list. This way the helper never silently
    # overwrites an existing file the user customised.
    return {"_legacy": raw, "chapters": []}


def append_summary(
    project_root: Path,
    chapter_id: str,
    summary: str,
    *,
    atomic: bool = True,
) -> Path:
    """Append a chapter summary to ``chapter_summaries.json``.

    Args:
        project_root: Path to the writer project root (must contain
            ``AGENT.md``).
        chapter_id: Stable chapter identifier (e.g. ``"1.1"``).
        summary: One-paragraph summary string. May contain newlines;
            the JSON writer handles escaping.
        atomic: When True (default), write via ``tempfile`` +
            ``os.replace`` so concurrent readers never observe a
            half-written file. Set to False only in tests that need
            to inspect intermediate failure modes.

    Returns:
        The path to the updated ``chapter_summaries.json``.

    Raises:
        ChapterSummariesError: When ``project_root`` is not a valid
            writer project, or when the atomic write fails.
    """
    if not _is_project_root(project_root):
        msg = (
            f"chapter_summaries.append_summary: {project_root} 不是有效的项目根"
            "（缺少 AGENT.md）"
        )
        raise ChapterSummariesError(msg)
    if not chapter_id or not chapter_id.strip():
        raise ChapterSummariesError("chapter_id 不能为空")
    if summary is None:
        raise ChapterSummariesError("summary 不能为 None")

    target = project_root / SUMMARIES_FILE
    payload = _read_existing(target)
    entry: dict[str, Any] = {
        "chapter_id": chapter_id.strip(),
        "summary": summary,
        "written_at": _now_iso(),
    }
    # Replace any prior entry with the same chapter_id (idempotent on
    # retry). Otherwise append.
    chapters: list[dict[str, Any]] = payload.setdefault("chapters", [])
    chapters = [c for c in chapters if c.get("chapter_id") != entry["chapter_id"]]
    chapters.append(entry)
    payload["chapters"] = chapters

    serialised = json.dumps(payload, ensure_ascii=False, indent=2)
    if not atomic:
        target.write_text(serialised, encoding="utf-8")
        return target

    # Atomic write: temp file in the same directory (so ``os.replace``
    # is an atomic rename, not a cross-filesystem copy).
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".chapter_summaries.", suffix=".tmp", dir=str(project_root)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(serialised)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path_str, target)
    except Exception:
        # Best-effort cleanup on failure; do not shadow the original error.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path_str)
        raise
    return target


__all__ = [
    "ChapterSummariesError",
    "SUMMARIES_FILE",
    "append_summary",
]
