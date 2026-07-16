"""项目状态检测。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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


_OUTLINE_PATHS = (
    # 新中文路径（per 2026-07-14 目录统一）—— 仅"大纲.md"视为正典大纲
    Path("大纲") / "大纲.md",
    # legacy 英文路径（向后兼容旧项目）
    Path("outline") / "大纲.md",
)
_TOC_PATHS = (
    # 新中文路径
    Path("大纲") / "章节目录.md",
    # legacy 英文路径
    Path("outline") / "toc.md",
    Path("目录") / "目录.md",
)
_MANUSCRIPT_DIRS = (
    # 新中文路径:草稿(工作中)+ 正文(定稿),两个独立
    Path("草稿"),
    Path("正文"),
    # legacy 英文 / 别名(向后兼容旧项目)
    Path("manuscript"),
    Path("正文草稿"),
)

#: ``AGENT.md`` 内状态块的 header。导出供写入工具（例如
#: :class:`writer.tools.builtin.file_tools.SafeWriteFile`）使用，让
#: 它们能校验 ``AGENT.md`` 写入保留项目所需结构，而无需在两处硬编码
#: 字面量（per ``chg-add-write-edit-glob`` D4）。
CURRENT_STATE_SECTION_HEADER = "## 当前状态"


#: ``架构方法:`` 行写入 ``AGENT.md`` 的默认值（per 2026-07-16 用户选
#: 择「雪花法」作为默认），与 :func:`render_agent_file` 的默认参数对齐。
#: ``/大纲`` directive 通过 ``safe_read_file`` 读 AGENT.md，缺失该行
#: 时回退到此值。
DEFAULT_ARCHITECTURE_METHOD: str = "雪花法"


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
    architecture_method: str = DEFAULT_ARCHITECTURE_METHOD,
) -> str:
    """渲染项目控制文件，供状态检测使用。

    当 ``genre`` 是已知题材（不是 ``"other"``）时，在状态行正下方
    包含一行 ``题材: <genre>``，让下游代码（``Engine.refresh_project_genre``
    和 CLI ``new`` / REPL brief 流程）可以通过简单正则拿到。默认 ``"other"``
    跳过这一行，保持遗留 ``AGENT.md`` 内容不变。

    ``architecture_method``（per 2026-07-16 落地）控制 ``/大纲`` directive
    选用的整体架构方法（雪花法 / 三幕结构 / 英雄之旅 / 三步八段式 /
    三明治 / 布莱克节拍表 / 起承转合 / 反套路等）。默认为 ``雪花法`` ，
    与项目「大纲最扎实」的定位匹配。该字段总会被渲染（非题材语义——
    即便方法退回默认"雪花法"，仍显式写入让下游 /大纲 directive 能稳定
    读取），与题材的"other 跳过"语义不同。

    reference：``docs/写作方法论/写作架构方法.md`` 列出全部可选方法。
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
    # 架构方法始终渲染（不像题材有"other 跳过"语义）—— 即便与默认相同
    # 也写一行，下游 ``/大纲`` directive 用 ``safe_read_file`` 能稳定读到。
    lines.append(f"- 架构方法: {architecture_method}\n")
    lines.extend(
        [
            "\n",
            "## 目录约定\n",
            "\n",
            "- 大纲/: 大纲、目录与分卷规划\n",
            "- 草稿/: 写作中的正文草稿\n",
            "- 正文/: 已定稿的正文\n",
            "- 人物/: 人物设定\n",
            "- 世界观/: 世界观设定\n",
            "- 备忘/: 写作笔记\n",
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

    保留文件中已有的 ``题材:`` 行与 ``架构方法:`` 行，让状态切换后
    （例如 S1 → S2）重新渲染不会清掉 ``create_workspace(...)`` /
    ``update_agent_*_line(...)`` 设置的元数据。

    当文件没有 ``架构方法:`` 行（遗留 / 手工改过）时回退到默认雪花法
    —— 不会写入 ``other`` 这种隐式值。
    """

    root = project_root.resolve()
    state = detect_state(root)
    project_name = root.name
    existing_genre = read_genre_from_agent(root / "AGENT.md")
    existing_method = read_architecture_method_from_agent(root / "AGENT.md")
    (root / "AGENT.md").write_text(
        render_agent_file(
            project_name,
            state,
            genre=existing_genre,
            architecture_method=existing_method,
        ),
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
        stripped = _strip_genre_line_prefix(line.strip())
        if stripped.startswith("题材:"):
            value = stripped.split(":", 1)[1].strip()
            return value or "other"
    return "other"


#: 可选的 Markdown 列表前缀集合，让 ``题材:`` 行可以以裸形式（``题材: 历史``）
#: 或列表项形式（``- 题材: 历史`` / ``* 题材: 历史`` / ``· 题材: 历史`` /
#: ``• 题材: 历史``）出现而不破坏解析。:func:`read_genre_from_agent` 与
#: :func:`update_agent_genre_line` 共用这一常量，避免列表漂移。
#: 2026-07-16 扩展：架构方法行（``架构方法: ...``）共用同一前缀规则。
_GENRE_LINE_PREFIXES: tuple[str, ...] = ("- ", "* ", "· ", "• ")


def _strip_genre_line_prefix(stripped: str) -> str:
    """去掉 ``题材:`` / ``架构方法:`` 行的可选 Markdown 列表前缀。"""

    for prefix in _GENRE_LINE_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].lstrip()
    return stripped


def update_agent_genre_line(agent_md: Path, genres: list[str]) -> bool:
    """原地更新 ``AGENT.md`` 中的 ``题材:`` 行，保留其它所有内容。

    与 :func:`refresh_agent_file` 的区别：本函数是**局部**更新，不重写
    AGENT.md 整体内容 —— ``## 基本要求`` 等下游段（由
    :func:`append_agent_requirements` 追加）得到保留。

    处理策略：

    1. ``format_genre_line(genres)`` 返回 ``None``（即全 ``other`` /
       空列表）时**移除**现有 ``题材:`` 行，让 ``read_genre_from_agent``
       回退到 ``"other"`` 兜底。
    2. 否则：

       - 若文件已存在 ``题材: ...`` 行（容忍 ``- `` / ``* `` / ``· `` /
         ``• `` 前缀，与 :func:`read_genre_from_agent` 一致），就地替换。
       - 若文件没有该行，则在第一个 ``## ...`` 二级标题前插入
         ``- 题材: <label>\\n`` —— 找不到任何二级标题时追加到末尾。

    返回 ``True`` 表示文件被改动，``False`` 表示 no-op（无 ``题材:``
    行可改且无须新增，或新值与旧值相同）。

    文件不存在时静默忽略（视为 no-op），不抛异常 —— 调用方需要
    提前用 :func:`create_workspace` 等保证 AGENT.md 存在。
    """

    from writer.project.genre import format_genre_line

    label = format_genre_line(genres)
    try:
        original = agent_md.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False

    lines = original.splitlines(keepends=True)

    # 第一遍：寻找现有 ``题材:`` 行的索引（与 ``read_genre_from_agent``
    # 共用 :func:`_strip_genre_line_prefix` 的前缀容忍规则）。
    target_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = _strip_genre_line_prefix(line.strip())
        if stripped.startswith("题材:"):
            target_idx = idx
            break

    if label is None:
        # 移除现有行（如果存在）；无现有行是 no-op。
        if target_idx is None:
            return False
        del lines[target_idx]
        agent_md.write_text("".join(lines), encoding="utf-8")
        return True

    new_line = f"- 题材: {label}\n"

    if target_idx is not None:
        # 就地替换 —— 即使新值与旧值相同也写一次以保证尾换行一致；
        # 调用方按返回值判断是否变更。
        if lines[target_idx] == new_line:
            return False
        lines[target_idx] = new_line
        agent_md.write_text("".join(lines), encoding="utf-8")
        return True

    # 没有 ``题材:`` 行：插入到第一个 ``## ...`` 二级标题之前。
    insert_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            insert_idx = idx
            break
    if insert_idx is None:
        # 没有任何二级标题 —— 追加到末尾。
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        lines.append(new_line)
    else:
        # 在标题前留一个空行（若上一行不是空行）。
        prefix = lines[:insert_idx]
        suffix = lines[insert_idx:]
        if prefix and prefix[-1].strip():
            prefix.append("\n")
        lines = prefix + [new_line, "\n"] + suffix

    agent_md.write_text("".join(lines), encoding="utf-8")
    return True


def read_architecture_method_from_agent(agent_md: Path) -> str:
    """从 ``AGENT.md`` 文件中解析 ``架构方法:`` 行。

    文件缺失、不可读或没有 ``架构方法:`` 行时回退到
    :data:`DEFAULT_ARCHITECTURE_METHOD`（雪花法）—— 与
    :func:`render_agent_file` 的默认参数对齐，下游 ``/大纲`` directive
    永远能拿到一个非空值。从不抛异常。

    两端空白会被去掉；可选的 Markdown 列表前缀（``- `` / ``* `` / ``· `` /
    ``• ``）也会被容忍，与 :func:`read_genre_from_agent` 共用前缀规则。
    """

    try:
        text = agent_md.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return DEFAULT_ARCHITECTURE_METHOD
    for line in text.splitlines():
        stripped = _strip_genre_line_prefix(line.strip())
        if stripped.startswith("架构方法:"):
            value = stripped.split(":", 1)[1].strip()
            return value or DEFAULT_ARCHITECTURE_METHOD
    return DEFAULT_ARCHITECTURE_METHOD


def update_agent_architecture_method_line(
    agent_md: Path, method: str
) -> bool:
    """原地更新 ``AGENT.md`` 中的 ``架构方法:`` 行，保留其它所有内容。

    与 :func:`update_agent_genre_line` 对称 —— 局部更新不重写整体，但
    比题材更新简单：架构方法没有"other 跳过"语义，
    :data:`DEFAULT_ARCHITECTURE_METHOD` 本身就是合法值，所以始终插入
    或替换、空字符串视为 no-op。

    处理策略：

    1. ``method`` 为空 / 纯空白 → no-op（不写也不删），返回 ``False``。
    2. 若文件已存在 ``架构方法: ...`` 行（容忍 ``- `` / ``* `` / ``· `` /
       ``• `` 前缀，与 :func:`read_architecture_method_from_agent` 一致），
       就地替换。
    3. 若文件没有该行，则在第一个 ``## ...`` 二级标题前插入
       ``- 架构方法: <method>\\n`` —— 找不到任何二级标题时追加到末尾。

    返回 ``True`` 表示文件被改动，``False`` 表示 no-op（空输入或
    新值与旧值相同）。

    文件不存在时静默忽略（视为 no-op），不抛异常 —— 调用方需要
    提前用 :func:`create_workspace` 等保证 AGENT.md 存在。
    """

    label = (method or "").strip()
    if not label:
        return False

    try:
        original = agent_md.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False

    lines = original.splitlines(keepends=True)

    # 第一遍：寻找现有 ``架构方法:`` 行的索引（共用 list-prefix 容忍规则）。
    target_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = _strip_genre_line_prefix(line.strip())
        if stripped.startswith("架构方法:"):
            target_idx = idx
            break

    new_line = f"- 架构方法: {label}\n"

    if target_idx is not None:
        if lines[target_idx] == new_line:
            return False
        lines[target_idx] = new_line
        agent_md.write_text("".join(lines), encoding="utf-8")
        return True

    # 没有 ``架构方法:`` 行：插入到第一个 ``## ...`` 二级标题之前。
    insert_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            insert_idx = idx
            break
    if insert_idx is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        lines.append(new_line)
    else:
        prefix = lines[:insert_idx]
        suffix = lines[insert_idx:]
        if prefix and prefix[-1].strip():
            prefix.append("\n")
        lines = prefix + [new_line, "\n"] + suffix

    agent_md.write_text("".join(lines), encoding="utf-8")
    return True


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
    "CURRENT_STATE_SECTION_HEADER",
    "ProjectSnapshot",
    "ProjectState",
    "STATE_DESCRIPTIONS",
    "append_agent_requirements",
    "count_chapters",
    "detect_state",
    "discover_project_root",
    "find_outline_path",
    "inspect_project",
    "read_genre_from_agent",
    "read_architecture_method_from_agent",
    "refresh_agent_file",
    "render_agent_file",
    "safe_cwd",
    "update_agent_genre_line",
    "update_agent_architecture_method_line",
    "DEFAULT_ARCHITECTURE_METHOD",
]
