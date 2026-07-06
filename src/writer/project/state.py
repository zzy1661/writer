"""Project state detection and command availability rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ProjectState(StrEnum):
    """Coarse-grained writing project lifecycle."""

    UNINITIALIZED = "S0"
    INITIALIZED = "S1"
    HAS_OUTLINE = "S2"
    HAS_TOC = "S3"
    WRITING = "S4"
    FINISHED = "S5"


STATE_DESCRIPTIONS: dict[ProjectState, str] = {
    ProjectState.UNINITIALIZED: "未初始化",
    ProjectState.INITIALIZED: "已初始化",
    ProjectState.HAS_OUTLINE: "已有大纲",
    ProjectState.HAS_TOC: "已有目录",
    ProjectState.WRITING: "写作中",
    ProjectState.FINISHED: "已完成",
}


@dataclass(frozen=True)
class ProjectSnapshot:
    """Readable summary of the current project on disk."""

    root: Path | None
    state: ProjectState
    chapter_count: int
    outline_path: Path | None = None


@dataclass(frozen=True)
class CommandCheck:
    """Result of checking whether a command can run in the current state."""

    command: str
    state: ProjectState
    ok: bool
    reason: str = ""


_OUTLINE_PATHS = (
    Path("outline") / "大纲.md",
    Path("大纲") / "大纲.md",
)
_TOC_PATHS = (
    Path("outline") / "toc.md",
    Path("目录") / "目录.md",
)
_MANUSCRIPT_DIRS = (
    Path("manuscript"),
    Path("正文草稿"),
    Path("正文"),
)

COMMAND_ALLOWED: dict[str, set[ProjectState]] = {
    "/init": {ProjectState.UNINITIALIZED},
    "/大纲": {ProjectState.INITIALIZED, ProjectState.HAS_OUTLINE},
    "/目录": {ProjectState.HAS_OUTLINE, ProjectState.HAS_TOC},
    "/写": {ProjectState.HAS_TOC, ProjectState.WRITING},
    "/续写": {ProjectState.WRITING},
    "/改": {ProjectState.WRITING},
    "/审核": {ProjectState.WRITING, ProjectState.FINISHED},
    "/查看": {
        ProjectState.INITIALIZED,
        ProjectState.HAS_OUTLINE,
        ProjectState.HAS_TOC,
        ProjectState.WRITING,
        ProjectState.FINISHED,
    },
    "/搜索": {
        ProjectState.INITIALIZED,
        ProjectState.HAS_OUTLINE,
        ProjectState.HAS_TOC,
        ProjectState.WRITING,
        ProjectState.FINISHED,
    },
    "/字数统计": {
        ProjectState.INITIALIZED,
        ProjectState.HAS_OUTLINE,
        ProjectState.HAS_TOC,
        ProjectState.WRITING,
        ProjectState.FINISHED,
    },
}

COMMAND_HINTS: dict[str, str] = {
    "/init": "当前已经绑定项目；如需新项目，请先退出当前 REPL 或另开目录。",
    "/大纲": "请先执行 /init <项目名> 创建项目。",
    "/目录": "请先用 /大纲 生成并落盘大纲。",
    "/写": "请先生成章节目录；当前 MVP 还不会从大纲自动生成目录。",
    "/续写": "请先进入写作中状态，也就是至少有一章正文草稿。",
    "/改": "请先进入写作中状态，也就是至少有一章正文草稿。",
    "/审核": "请先写出至少一章正文。",
    "/查看": "请先执行 /init <项目名> 创建项目。",
    "/搜索": "请先执行 /init <项目名> 创建项目。",
    "/字数统计": "请先执行 /init <项目名> 创建项目。",
}


def detect_state(project_root: Path | None) -> ProjectState:
    """Infer the project lifecycle state from files under ``project_root``."""

    if project_root is None:
        return ProjectState.UNINITIALIZED

    root = project_root.resolve()
    if not (root / "AGENT.md").is_file():
        return ProjectState.UNINITIALIZED

    if _has_markdown_in_any(root, _MANUSCRIPT_DIRS):
        return ProjectState.WRITING

    if _first_existing_nonempty(root, _TOC_PATHS) is not None:
        return ProjectState.HAS_TOC

    if _first_existing_nonempty(root, _OUTLINE_PATHS) is not None:
        return ProjectState.HAS_OUTLINE

    return ProjectState.INITIALIZED


def inspect_project(project_root: Path | None) -> ProjectSnapshot:
    """Return a display-ready snapshot for ``/状态``."""

    state = detect_state(project_root)
    if project_root is None:
        return ProjectSnapshot(
            root=None,
            state=state,
            chapter_count=0,
            outline_path=None,
        )

    root = project_root.resolve()
    return ProjectSnapshot(
        root=root,
        state=state,
        chapter_count=count_chapters(root),
        outline_path=_first_existing_nonempty(root, _OUTLINE_PATHS),
    )


def validate_command_available(
    command: str | None,
    project_root: Path | None,
    project_state: str | ProjectState | None = None,
) -> CommandCheck:
    """Validate a slash command against the state matrix.

    Unknown commands stay pass-through for the existing ``command_pending``
    branch; only commands declared in ``COMMAND_ALLOWED`` are blocked.
    """

    state = _coerce_state(project_state) if project_root is None else detect_state(project_root)
    if command not in COMMAND_ALLOWED:
        return CommandCheck(command=command or "", state=state, ok=True)

    allowed = COMMAND_ALLOWED[command]
    if state in allowed:
        return CommandCheck(command=command, state=state, ok=True)

    description = STATE_DESCRIPTIONS[state]
    hint = COMMAND_HINTS.get(command, "请先推进项目到可用状态。")
    return CommandCheck(
        command=command,
        state=state,
        ok=False,
        reason=f"{command} 当前不可用：项目状态为 {state.value}（{description}）。{hint}",
    )


def count_chapters(project_root: Path) -> int:
    """Count markdown drafts in known manuscript directories."""

    total = 0
    for directory in _MANUSCRIPT_DIRS:
        target = project_root / directory
        if target.is_dir():
            total += sum(1 for path in target.glob("*.md") if _is_nonempty_file(path))
    return total


def render_agent_file(project_name: str, state: ProjectState) -> str:
    """Render the project control file used by state detection."""

    return (
        f"# {project_name}\n\n"
        "Writer Agent 项目状态文件。\n\n"
        "## 当前状态\n\n"
        f"- state: {state.value}\n"
        f"- label: {STATE_DESCRIPTIONS[state]}\n\n"
        "## 目录约定\n\n"
        "- outline/: 大纲、目录与分卷规划\n"
        "- manuscript/: 正文草稿\n"
        "- characters/: 人物设定\n"
        "- world/: 世界观设定\n"
        "- notes/: 写作笔记\n"
    )


def refresh_agent_file(project_root: Path) -> None:
    """Update ``AGENT.md`` with the current detected state."""

    root = project_root.resolve()
    state = detect_state(root)
    project_name = root.name
    (root / "AGENT.md").write_text(
        render_agent_file(project_name, state),
        encoding="utf-8",
    )


def _coerce_state(value: str | ProjectState | None) -> ProjectState:
    if isinstance(value, ProjectState):
        return value
    if value is None:
        return ProjectState.UNINITIALIZED
    try:
        return ProjectState(value)
    except ValueError:
        return ProjectState.UNINITIALIZED


def _first_existing_nonempty(root: Path, relatives: tuple[Path, ...]) -> Path | None:
    for relative in relatives:
        candidate = root / relative
        if _is_nonempty_file(candidate):
            return candidate
    return None


def _has_markdown_in_any(root: Path, relatives: tuple[Path, ...]) -> bool:
    for relative in relatives:
        directory = root / relative
        if not directory.is_dir():
            continue
        if any(_is_nonempty_file(path) for path in directory.glob("*.md")):
            return True
    return False


def _is_nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


__all__ = [
    "COMMAND_ALLOWED",
    "CommandCheck",
    "ProjectSnapshot",
    "ProjectState",
    "STATE_DESCRIPTIONS",
    "count_chapters",
    "detect_state",
    "inspect_project",
    "refresh_agent_file",
    "render_agent_file",
    "validate_command_available",
]
