"""项目状态检测与命令可用性规则。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


class ProjectState(StrEnum):
    """粗粒度的写作项目生命周期。"""

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
    """磁盘上当前项目的可读摘要。"""

    root: Path | None
    state: ProjectState
    chapter_count: int
    outline_path: Path | None = None


@dataclass(frozen=True)
class CommandCheck:
    """检查某命令在当前状态下是否可运行的结果。"""

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

#: ``AGENT.md`` 内状态块的 header。导出供写入工具（例如
#: :class:`writer.tools.builtin.file_tools.SafeWriteFile`）使用，让
#: 它们能校验 ``AGENT.md`` 写入保留项目所需结构，而无需在两处硬编码
#: 字面量（per ``chg-add-write-edit-glob`` D4）。
CURRENT_STATE_SECTION_HEADER = "## 当前状态"

COMMAND_ALLOWED: dict[str, set[ProjectState]] = {
    # 注：/大纲, /目录 故意缺席 —— 它们是 Skill-backed 命令，
    # 可用性从注册 Skill 的 ``requires_states`` 派生。
    # 见 ``validate_command_available`` + ``SkillRegistryView``。
    "/init": {ProjectState.UNINITIALIZED},
    "/创作": {ProjectState.HAS_TOC, ProjectState.WRITING},
    "/审核": {ProjectState.WRITING, ProjectState.FINISHED},
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
    "/字数统计": "请先执行 /init <项目名> 创建项目。",
}


def safe_cwd() -> Path | None:
    """返回当前工作目录；不可用时返回 ``None``。"""

    try:
        return Path.cwd()
    except OSError:
        return None


def find_outline_path(project_root: Path) -> Path | None:
    """返回 ``project_root`` 下第一个非空大纲文件。"""

    return _first_existing_nonempty(project_root.resolve(), _OUTLINE_PATHS)


def discover_project_root(start: Path | None = None) -> Path | None:
    """在 ``start`` 附近寻找小说项目根目录（默认：cwd）。

    当包含 ``AGENT.md`` 时返回 ``start``。否则，当恰好一个直接子目录
    包含 ``AGENT.md`` 时返回该子目录。布局歧义或缺失时返回 ``None``。
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
    """从 ``project_root`` 下的文件推断项目生命周期状态。"""

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
    """为 ``/状态`` 返回一份展示用的快照。"""

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
    """根据状态矩阵校验斜杠命令。

    可用性集合的查找顺序：

    1. ``skill_registry.state_matrix()`` —— 驱动 Skill 绑定命令
       （``/大纲`` / ``/目录``），让状态矩阵完全从 Skill 元数据派生。
    2. ``COMMAND_ALLOWED`` —— 不属于任何 Skill 的命令的静态回退
       （``/init`` 本身以及仍手写的工具 / 工作流命令）。

    未知命令保持原样走向 ``command_pending`` 分支；只有在这两个
    来源中声明过的命令会被拦截。
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
    """:class:`writer.skills.registry.SkillRegistry` 的结构视图。

    在此定义（而非从 ``writer.skills`` 引入）以让 :mod:`writer.project.state`
    不依赖较重的 skill 依赖。完整的
    :class:`writer.skills.registry.SkillRegistry` 平凡地满足该 Protocol，
    因为这两个方法都是它的公开 API。
    """

    def state_matrix(self) -> dict[str, frozenset[ProjectState]]:
        ...


def _skill_hint(command: str) -> str:
    """把 Skill 驱动的命令映射为面向用户的提示字符串。

    在此保留（而非放在 :mod:`writer.skills`）让状态矩阵只在能查到
    同一命令的注册表时才报告 —— 避免把 skill 端的翻译表拉进静态
    :data:`COMMAND_HINTS` 回退。
    """

    return {
        "/大纲": "请先执行 /init <项目名> 创建项目。",
        "/目录": "请先用 /大纲 生成并落盘大纲。",
    }.get(command, "请先推进项目到可用状态。")


def count_chapters(project_root: Path) -> int:
    """统计已知 manuscript 目录中的 markdown 草稿数。"""

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
    """渲染项目控制文件，供状态检测使用。

    当 ``genre`` 是已知题材（不是 ``"other"``）时，在状态行正下方
    包含一行 ``题材: <genre>``，让下游代码（``EngineSession.refresh_project_genre``
    和 CLI ``init_project``）可以通过简单正则拿到。默认 ``"other"``
    跳过这一行，保持遗留 ``AGENT.md`` 内容不变。
    """

    lines = [
        f"# {project_name}\n",
        "\n",
        "Writer Agent 项目状态文件。\n",
        "\n",
        f"{CURRENT_STATE_SECTION_HEADER}\n",
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
    """在 ``AGENT.md`` 中追加或替换 ``## 基本要求`` 段。"""

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
    """用当前检测到的状态更新 ``AGENT.md``。

    保留文件中已有的 ``题材:`` 行，让状态切换后（例如 S1 → S2）
    重新渲染不会清掉 ``create_workspace(genre=...)`` 设置的题材。
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
    """从 ``AGENT.md`` 文件中解析 ``题材:`` 行。

    文件缺失、不可读或没有 ``题材:`` 行时返回 ``"other"`` —— 从不抛异常。
    两端空白会被去掉；可选的 Markdown 列表前缀（``- `` / ``* ``）
    也会被容忍，让解析对 ``render_agent_file`` 格式变化保持健壮。
    """

    try:
        text = agent_md.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return "other"
    for line in text.splitlines():
        stripped = line.strip()
        # 容忍前导列表字符，让该行可以以 ``题材: 历史`` 或
        # ``- 题材: 历史`` 两种形式出现而不破坏解析。
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
