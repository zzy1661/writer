"""``chapter_summaries.json`` 的原子写入辅助函数。

``write_chapter`` 工作流（real-writing-pipeline PR2）在写完章节草稿
后，向项目的 ``chapter_summaries.json`` 追加每章摘要。本辅助函数：

* 加载既有 JSON（新项目初始化为 ``{"chapters": []}``）。
* 追加新条目：``{"chapter_id", "summary", "written_at"}``。
* **原子地**写入文件（tempfile + ``os.replace``），让并发读取者
  （例如 REPL 每轮的 canon-block 构建器）永远不会观察到半写入文件。

本函数刻意收窄并限定项目范围：它位于 ``writer.project``，因为
``chapter_summaries.json`` 是项目产物（被 canon block 读取，被工作流
写入）。它*不*调用 ``safe_write_file``，因为该文件是 JSON 且需要
read-modify-write 语义；Tool 层需要为这种形态添加另一种 mode。

2026-07-09 增补（real-writing-pipeline PR2）。
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
    """当 chapter_summaries 辅助函数无法操作时抛出。

    继承自 ``ValueError``（与本包其他领域异常一致），让引擎的
    ``except Exception`` 分支把它作为普通的 aborted 轮次暴露。
    """


def _is_project_root(path: Path) -> bool:
    """当 ``path`` 看起来像 writer 项目根时返回 True。

    校验刻意保持廉价：项目标记是 ``AGENT.md``（始终由
    :func:`writer.project.create_workspace` 写入）。
    """
    return (path / "AGENT.md").exists()


def _now_iso() -> str:
    """以 ISO 8601 + ``Z`` 后缀格式返回当前 UTC 时间。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_existing(path: Path) -> dict[str, Any]:
    """若存在则加载既有 ``chapter_summaries.json``。

    返回规范化后的 ``{"chapters": [...]}`` 形态。若既有文件使用不同
    形态（遗留迁移情形），原 payload 会被保存在 ``"_legacy"`` 下，
    不丢失任何数据。
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
    # 遗留形态：把原始内容存在 ``_legacy`` 下，并启用新的
    # ``chapters`` 列表。这样本辅助函数绝不会静默覆盖用户定制
    # 的现有文件。
    return {"_legacy": raw, "chapters": []}


def append_summary(
    project_root: Path,
    chapter_id: str,
    summary: str,
    *,
    atomic: bool = True,
) -> Path:
    """向 ``chapter_summaries.json`` 追加一条章节摘要。

    Args:
        project_root: writer 项目根路径（必须含 ``AGENT.md``）。
        chapter_id: 稳定的章节标识符（例如 ``"1.1"``）。
        summary: 一段摘要字符串。可以包含换行；JSON writer
            会处理转义。
        atomic: 为 True（默认）时，通过 ``tempfile`` + ``os.replace``
            写入，让并发读取者不会观察到半写入文件。仅在需要检查
            中间失败模式的测试中设为 False。

    Returns:
        更新后的 ``chapter_summaries.json`` 路径。

    Raises:
        ChapterSummariesError: 当 ``project_root`` 不是有效的
            writer 项目，或原子写入失败时。
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
    # 替换任何相同 chapter_id 的旧条目（重试时幂等）。
    # 否则追加。
    chapters: list[dict[str, Any]] = payload.setdefault("chapters", [])
    chapters = [c for c in chapters if c.get("chapter_id") != entry["chapter_id"]]
    chapters.append(entry)
    payload["chapters"] = chapters

    serialised = json.dumps(payload, ensure_ascii=False, indent=2)
    if not atomic:
        target.write_text(serialised, encoding="utf-8")
        return target

    # 原子写入：临时文件位于同一目录（让 ``os.replace`` 是原子
    # 重命名，而非跨文件系统拷贝）。
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
        # 失败时尽力清理；不要遮蔽原始错误。
        with contextlib.suppress(OSError):
            os.unlink(tmp_path_str)
        raise
    return target


__all__ = [
    "ChapterSummariesError",
    "SUMMARIES_FILE",
    "append_summary",
]
