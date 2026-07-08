"""Project state detection and command availability rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


class ProjectState(StrEnum):
    """Coarse-grained writing project lifecycle."""

    UNINITIALIZED = "S0"
    INITIALIZED = "S1"
    HAS_OUTLINE = "S2"
    HAS_TOC = "S3"
    WRITING = "S4"
    FINISHED = "S5"


STATE_DESCRIPTIONS: dict[ProjectState, str] = {
    ProjectState.UNINITIALIZED: "待启动",
    ProjectState.INITIALIZED: "初始化",
    ProjectState.HAS_OUTLINE: "大纲拟定中",
    ProjectState.HAS_TOC: "框架搭建中",
    ProjectState.WRITING: "正文编辑中",
    ProjectState.FINISHED: "审核中",
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
    # NOTE: /大纲, /目录, /续写, /改 are intentionally absent — they are
    # Skill-backed commands whose availability is derived from the
    # registered Skill's `requires_states`. See
    # ``validate_command_available`` + ``SkillRegistryView``.
    "/init": {ProjectState.UNINITIALIZED},
    "/创作": {ProjectState.HAS_TOC, ProjectState.WRITING},
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
    "/init": (
        "当前已经绑定项目。填写故事创意请直接输入 /init <故事梗概>；"
        "如需新建项目，请先退出当前 REPL 或另开目录。"
    ),
    "/创作": "请先生成章节目录；当前 MVP 还不会从大纲自动生成目录。",
    "/审核": "请先写出至少一章正文。",
    "/查看": "请先执行 /init <项目名> 创建项目。",
    "/搜索": "请先执行 /init <项目名> 创建项目。",
    "/字数统计": "请先执行 /init <项目名> 创建项目。",
}


def safe_cwd() -> Path | None:
    """Return the current working directory, or ``None`` when it is unavailable."""

    try:
        return Path.cwd()
    except OSError:
        return None


def find_outline_path(project_root: Path) -> Path | None:
    """Return the first non-empty outline file under ``project_root``."""

    return _first_existing_nonempty(project_root.resolve(), _OUTLINE_PATHS)


def discover_project_root(start: Path | None = None) -> Path | None:
    """Find a novel project root near ``start`` (default: cwd).

    Returns ``start`` when it contains ``AGENT.md``. Otherwise, when
    exactly one immediate child directory contains ``AGENT.md``, returns
    that child. Ambiguous or missing layouts return ``None``.
    """

    if start is None:
        start = safe_cwd()
        if start is None:
            return None

    try:
        base = start.resolve()
    except OSError:
        return None

    if not base.is_dir():
        return None

    if (base / "AGENT.md").is_file():
        return base

    try:
        children = base.iterdir()
    except OSError:
        return None

    candidates = sorted(
        child
        for child in children
        if child.is_dir() and (child / "AGENT.md").is_file()
    )
    if len(candidates) == 1:
        return candidates[0]
    return None


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
    *,
    skill_registry: SkillRegistryView | None = None,
) -> CommandCheck:
    """Validate a slash command against the state matrix.

    Lookup order for the availability set:

    1. ``skill_registry.state_matrix()`` — drives the Skill-bound
       commands (``/大纲`` / ``/目录`` / ``/续写`` / ``改``) so the
       state matrix is fully derived from Skill metadata.
    2. ``COMMAND_ALLOWED`` — the static fallback for commands that
       aren't owned by any Skill (``/init`` itself plus the tool- and
       workflow-backed commands still listed by hand).

    Unknown commands stay pass-through for the existing
    ``command_pending`` branch; only commands declared in either source
    are blocked.
    """

    state = _coerce_state(project_state) if project_root is None else detect_state(project_root)
    if not command:
        return CommandCheck(command="", state=state, ok=True)

    skill_matrix = skill_registry.state_matrix() if skill_registry is not None else {}
    if command in skill_matrix:
        skill_allowed = skill_matrix[command]
        if state in skill_allowed:
            return CommandCheck(command=command, state=state, ok=True)
        description = STATE_DESCRIPTIONS[state]
        hint = _skill_hint(command)
        return CommandCheck(
            command=command,
            state=state,
            ok=False,
            reason=f"{command} 当前不可用：项目状态为 {state.value}（{description}）。{hint}",
        )

    if command not in COMMAND_ALLOWED:
        return CommandCheck(command=command, state=state, ok=True)

    static_allowed = COMMAND_ALLOWED[command]
    if state in static_allowed:
        return CommandCheck(command=command, state=state, ok=True)

    description = STATE_DESCRIPTIONS[state]
    hint = COMMAND_HINTS.get(command, "请先推进项目到可用状态。")
    return CommandCheck(
        command=command,
        state=state,
        ok=False,
        reason=f"{command} 当前不可用：项目状态为 {state.value}（{description}）。{hint}",
    )


@runtime_checkable
class SkillRegistryView(Protocol):
    """Structural view of :class:`writer.skills.registry.SkillRegistry`.

    Defined here (not imported from ``writer.skills``) to keep
    :mod:`writer.project.state` free of the heavier skill dependencies.
    The full :class:`writer.skills.registry.SkillRegistry` trivially
    satisfies this Protocol because the two methods are part of its
    public surface.
    """

    def state_matrix(self) -> dict[str, frozenset[ProjectState]]:
        ...


def _skill_hint(command: str) -> str:
    """Map a Skill-driven command to a user-facing hint string.

    Kept here (not in :mod:`writer.skills`) so the state matrix only
    reports on a command when the same command can be looked up in the
    registry — this avoids pulling skill-side translation tables into
    the static :data:`COMMAND_HINTS` fallback.
    """

    return {
        "/大纲": "请先执行 /init <项目名> 创建项目。",
        "/目录": "请先用 /大纲 生成并落盘大纲。",
        "/续写": "请先进入正文编辑中状态，也就是至少有一章正文草稿。",
        "/改": "请先进入正文编辑中状态，也就是至少有一章正文草稿。",
    }.get(command, "请先推进项目到可用状态。")


def count_chapters(project_root: Path) -> int:
    """Count markdown drafts in known manuscript directories."""

    total = 0
    for directory in _MANUSCRIPT_DIRS:
        target = project_root / directory
        if target.is_dir():
            total += sum(1 for path in target.glob("*.md") if _is_nonempty_file(path))
    return total


def render_agent_file(
    project_name: str,
    state: ProjectState,
    *,
    genre: str = "other",
) -> str:
    """Render the project control file used by state detection.

    When ``genre`` is a known genre (not ``"other"``), a ``题材: <genre>``
    line is included directly below the state line so downstream code
    (``EngineSession.refresh_project_genre`` and CLI ``init_project``)
    can pick it up via simple regex. The default ``"other"`` skips the
    line to keep legacy ``AGENT.md`` content unchanged.
    """

    lines = [
        f"# {project_name}\n",
        "\n",
        "Writer Agent 项目状态文件。\n",
        "\n",
        "## 当前状态\n",
        "\n",
        f"- state: {state.value}\n",
        f"- label: {STATE_DESCRIPTIONS[state]}\n",
    ]
    if genre and genre != "other":
        lines.append(f"- 题材: {genre}\n")
    lines.extend(
        [
            "\n",
            "## 目录约定\n",
            "\n",
            "- outline/: 大纲、目录与分卷规划\n",
            "- manuscript/: 正文草稿\n",
            "- characters/: 人物设定\n",
            "- world/: 世界观设定\n",
            "- notes/: 写作笔记\n",
            "- 创意/: 故事创意与核心设定\n",
        ]
    )
    return "".join(lines)


def append_agent_requirements(agent_md: Path, requirements: str) -> None:
    """Append or replace the ``## 基本要求`` section in ``AGENT.md``."""

    section = "## 基本要求\n\n" + requirements.strip() + "\n"
    try:
        existing = agent_md.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        existing = ""

    marker = "## 基本要求"
    if marker in existing:
        before, _, _after = existing.partition(marker)
        updated = before.rstrip() + "\n\n" + section
    else:
        updated = existing.rstrip() + "\n\n" + section
    agent_md.write_text(updated, encoding="utf-8")


def refresh_agent_file(project_root: Path) -> None:
    """Update ``AGENT.md`` with the current detected state.

    Preserves any ``题材:`` line already in the file so re-rendering after
    a state transition (e.g. S1 → S2) doesn't clobber the genre set by
    ``create_workspace(genre=...)``.
    """

    root = project_root.resolve()
    state = detect_state(root)
    project_name = root.name
    existing_genre = read_genre_from_agent(root / "AGENT.md")
    (root / "AGENT.md").write_text(
        render_agent_file(project_name, state, genre=existing_genre),
        encoding="utf-8",
    )


def read_genre_from_agent(agent_md: Path) -> str:
    """Parse the ``题材:`` line out of an ``AGENT.md`` file.

    Returns ``"other"`` if the file is missing, unreadable, or has no
    ``题材:`` line — never raises. Whitespace is stripped on both sides;
    optional Markdown bullet prefix (``- `` / ``* ``) is tolerated so the
    parser is robust to ``render_agent_file`` formatting changes.
    """

    try:
        text = agent_md.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return "other"
    for line in text.splitlines():
        stripped = line.strip()
        # Tolerate a leading bullet character so the line can appear as
        # either ``题材: 历史`` or ``- 题材: 历史`` without breaking the parser.
        if stripped.startswith(("- ", "* ", "· ", "• ")):
            stripped = stripped[2:].lstrip()
        if stripped.startswith("题材:"):
            value = stripped.split(":", 1)[1].strip()
            return value or "other"
    return "other"


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
    "SkillRegistryView",
    "append_agent_requirements",
    "count_chapters",
    "detect_state",
    "discover_project_root",
    "find_outline_path",
    "inspect_project",
    "read_genre_from_agent",
    "refresh_agent_file",
    "render_agent_file",
    "safe_cwd",
    "validate_command_available",
]
