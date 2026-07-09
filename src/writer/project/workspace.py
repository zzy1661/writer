"""小说项目 workspace 脚手架。

``create_workspace`` 把小说项目的目录布局落到磁盘。基础布局
（``manuscript / outline / characters / world / notes`` +
``AGENT.md / README.md`` + 每个子目录一个 stub）是**与题材无关**的；
题材特定的额外内容（历史 ``史实/``、玄幻 ``伏笔/``、言情 ``人设/``）
由 :func:`_genre_scaffolding` 层叠上去，并合并到返回的
``created_files`` 列表中。

当 ``with_writer_meta=True``（即 :func:`create_new_workspace` 走的
``writer new`` 路径）时，:func:`_writer_meta_scaffolding`` 还会创建
``<root>/.writer/``，包含三个子区域：镜像 4 个内置 skills 的
``skills/`` 目录、空的 ``agents/`` 目录、以及 ``config`` env 风格文件。

题材值由 :func:`_normalize_genre` 规范化 —— 中文标签
（``历史 / 言情 / 玄幻``）与英文短形式（``history / romance /
xuanhuan``）映射到同一 key。其他所有值回退到 ``"other"``，产生
默认布局且不附加额外内容。

向后兼容性保留：不带显式 ``genre`` keyword 的
``create_workspace(name, base_dir)`` 行为与之前完全一致（其他回退）。
见 ``tests/test_workspace.py`` 中的契约。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

from writer.project.genre import format_genre_line, normalize_genres, primary_genre
from writer.project.state import ProjectState, render_agent_file

_WRITER_CONFIG_TEMPLATE = """\
# 项目级 LLM 配置（优先级高于 .env）
WRITER_MODEL=gpt-4o-mini
WRITER_API_KEY=
WRITER_BASE_URL=https://api.openai.com/v1
WRITER_TEMPERATURE=0.7
"""


@dataclass(frozen=True)
class NovelWorkspace:
    root: Path
    created_files: list[Path]


# 题材白名单 —— 必须与 CLI 提示选项保持同步。
# 接受英文短形式作为别名（小写、容忍前后空格）。
_GENRE_ALIASES: dict[str, str] = {
    "历史": "历史",
    "history": "历史",
    "historical": "历史",
    "言情": "言情",
    "romance": "言情",
    "玄幻": "玄幻",
    "xuanhuan": "玄幻",
    "fantasy": "玄幻",
    "other": "other",
    "其他": "other",
    "其它": "other",
}


def _normalize_genre(genre: str) -> str:
    """返回输入的规范题材 key。

    任何不在别名表中的值 —— 包括用户自定义字符串，例如 ``"都市悬疑"``
    或 ``"科幻"`` —— 都返回 ``"other"``。空 / 纯空白输入同样视为
    ``"other"``。
    """
    key = (genre or "").strip().lower()
    return _GENRE_ALIASES.get(key, "other")


def create_workspace(
    name: str,
    base_dir: Path,
    *,
    force: bool = False,
    genre: str = "other",
    genres: list[str] | None = None,
    with_ideas_dir: bool = False,
    with_writer_meta: bool = False,
    seed_agents: bool = False,
) -> NovelWorkspace:
    project_name = _normalize_name(name)
    genre_list = normalize_genres(genres if genres is not None else [genre])
    canonical_genre = primary_genre(genre_list)
    root = base_dir / project_name

    if root.exists() and not force:
        msg = (
            f"项目目录已存在: {root}。"
            f"如要覆盖请重新执行 `writer init {project_name} --force`，"
            f"或先手动删除/重命名该目录。"
        )
        raise FileExistsError(msg)

    directories = [
        root / "manuscript",
        root / "outline",
        root / "characters",
        root / "world",
        root / "notes",
    ]
    if with_ideas_dir:
        directories.append(root / "创意")
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    files = {
        root / "AGENT.md": render_agent_file(
            project_name,
            ProjectState.INITIALIZED,
            genre=format_genre_line(genre_list) or canonical_genre,
        ),
        root / "README.md": f"# {project_name}\n\n长篇小说项目工作区。\n",
        root / "outline" / "premise.md": "# 一句话创意\n\n",
        root / "outline" / "volume-plan.md": "# 分卷规划\n\n",
        root / "characters" / "main.md": "# 主要人物\n\n",
        root / "world" / "setting.md": "# 世界观设定\n\n",
        root / "notes" / "todo.md": "# 待办\n\n",
    }

    created_files: list[Path] = []
    for path, content in files.items():
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            created_files.append(path)

    if with_ideas_dir:
        ideas_stub = root / "创意" / "README.md"
        if force or not ideas_stub.exists():
            ideas_stub.write_text("# 创意库\n\n存放故事创意、灵感与核心设定。\n", encoding="utf-8")
            created_files.append(ideas_stub)

    # 题材特定脚手架叠在基础布局之上。
    created_files.extend(_genre_scaffolding(root, canonical_genre))

    if with_writer_meta:
        created_files.extend(
            _writer_meta_scaffolding(root, force=force, seed_agents=seed_agents)
        )

    return NovelWorkspace(root=root, created_files=created_files)


def create_new_workspace(
    name: str,
    base_dir: Path,
    *,
    force: bool = False,
    genres: list[str] | None = None,
) -> NovelWorkspace:
    """创建带 ``创意/`` 和 ``.writer/`` 元数据的小说项目。

    ``.writer/`` 元数据脚手架同时镜像 4 个内置 directives 与
    4 个内置 agents（per ``fea-agent-mirror``）。
    """

    return create_workspace(
        name,
        base_dir,
        force=force,
        genres=genres,
        with_ideas_dir=True,
        with_writer_meta=True,
        seed_agents=True,
    )


def _writer_meta_scaffolding(
    root: Path, *, force: bool = False, seed_agents: bool = False
) -> list[Path]:
    writer_root = root / ".writer"
    # 注：``agents/`` 不再是占位的 .gitkeep；下面的 _seed_agents 助手
    # 创建真实的 .md 文件。我们仍确保目录存在，让早于 agent mirror
    # 的项目（且已有 .gitkeep）不会被打断。
    targets = {
        writer_root / "skills" / ".gitkeep": "",
        writer_root / "config": _WRITER_CONFIG_TEMPLATE,
    }
    created: list[Path] = []
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)

    # 即使没有可发现的内置 agent（遗留 / S0 路径），也确保 agents
    # 目录存在。真正的 .md 落地后，seed 步骤会移除 .gitkeep。
    (writer_root / "agents").mkdir(parents=True, exist_ok=True)

    created.extend(_seed_directives(writer_root, force=force))
    if seed_agents:
        created.extend(_seed_agents(writer_root, force=force))
    return created


def _seed_agents(
    writer_root: Path, *, force: bool = False
) -> list[Path]:
    """把 4 个内置 agent ``.md`` 文件复制到项目中。

    每个内置 agent 位于
    ``writer.agents._shipped/<name>.md``（通过
    :mod:`importlib.resources` 加载）。本助手把每个 ``*.md`` 复制到
    ``<writer_root>/agents/``，让项目从一份完整的 4 个默认 agent
    可编辑副本开始。

    复制后，项目目录中包含与内置源相同的文件。发现层对内置与
    用户添加 agent 一视同仁 —— 用户可以自由编辑、删除或扩展。

    单文件失败以 WARNING 记录并跳过（让一份损坏的内置副本不阻塞
    其余）。磁盘上已存在的文件保持不变，除非 ``force=True``。

    仅当 ``with_writer_meta=True``（``create_new_workspace`` 路径）
    时由 :func:`_writer_meta_scaffolding` 调用。底层
    :func:`create_workspace` *不* 播种 agent。
    """

    agents_dir = writer_root / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # 本地 import：让 workspace 模块不含顶层 writer.agents 依赖
    # （避免未来潜在的循环 import 风险；与上方的 _seed_directives
    # 模式一致）。
    try:
        import importlib.resources as _resources
    except ImportError:  # pragma: no cover — Python 3.12+ 有
        return []

    created: list[Path] = []
    try:
        shipped_root = _resources.files("writer.agents._shipped")
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "Cannot locate shipped agents package: %s: %s; "
            "agent seeding skipped",
            type(exc).__name__,
            exc,
        )
        return []

    try:
        file_iter = sorted(
            (p for p in shipped_root.iterdir() if p.name.endswith(".md")),
            key=lambda p: p.name,
        )
    except (OSError, NotImplementedError) as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Cannot iterate shipped agents: %s: %s; "
            "agent seeding skipped",
            type(exc).__name__,
            exc,
        )
        return []

    for src_path in file_iter:
        target = agents_dir / src_path.name
        # Per ``fea-agent-mirror`` spec：永不覆盖已存在的 agent 文件
        # （即使 ``force=True``）。一旦镜像落地，用户的编辑就是
        # 真理之源；后续 ``writer new --force`` 对已有 agent 文件
        # 是 no-op。这比 directives 镜像更严格，因为 agent 携带项目
        # 特定身份（用户的定制 description / body），比通用 skill body
        # 更容易被定制。
        if target.exists():
            continue
        try:
            content = src_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Cannot read shipped agent file %s: %s; skipping",
                src_path,
                exc,
            )
            continue
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Cannot write shipped agent file %s: %s; skipping",
                target,
                exc,
            )
            continue
        created.append(target)

    # 整理：如果创建了真实的 .md 文件，而 agents 目录里还有陈旧的
    # .gitkeep 占位符，则移除它，让项目树不留令人困惑的空文件。
    if created:
        stale = agents_dir / ".gitkeep"
        if stale.is_file():
            with contextlib.suppress(OSError):
                stale.unlink()
    return created


def _seed_directives(
    writer_root: Path, *, force: bool = False
) -> list[Path]:
    """把 4 个内置 SKILL.md directive 包复制到项目中。

    每个内置 directive 位于
    ``writer.skills._shipped/<command>/``（通过
    :mod:`importlib.resources` 加载）。本助手把整个目录树 ——
    ``SKILL.md`` + ``references/*.md``（以及任何未来的
    ``scripts/*.py``）—— 复制到 ``<writer_root>/skills/<command>/``。

    复制后，项目目录中包含与内置源相同的文件。发现层对内置与
    用户添加 directive 一视同仁 —— 用户可以自由编辑、删除或扩展。

    单 directive 失败以 WARNING 记录并跳过（让一份损坏的内置副本
    不阻塞其余）。磁盘上已存在的文件保持不变，除非 ``force=True``。

    仅当 ``with_writer_meta=True``（``create_new_workspace`` 路径）
    时由 :func:`_writer_meta_scaffolding` 调用。底层
    :func:`create_workspace` *不* 播种 directive。
    """

    skills_dir = writer_root / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # 本地 import：让 workspace 模块不含顶层 writer.skills 依赖
    # （避免未来潜在的循环 import 风险）。
    try:
        import importlib.resources as _resources
    except ImportError:  # pragma: no cover — Python 3.12+ 有
        return []

    created: list[Path] = []
    try:
        shipped_root = _resources.files("writer.skills._shipped")
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "Cannot locate shipped directives package: %s: %s; "
            "directive seeding skipped",
            type(exc).__name__,
            exc,
        )
        return []

    try:
        sub_iter = sorted(
            (p for p in shipped_root.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
    except (OSError, NotImplementedError) as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Cannot iterate shipped directives: %s: %s; "
            "directive seeding skipped",
            type(exc).__name__,
            exc,
        )
        return []

    for sub in sub_iter:
        target_dir = skills_dir / sub.name
        for src_path in _walk_traversable(sub):
            rel = src_path.relative_to(sub).as_posix()
            target = target_dir / rel
            if (not force) and target.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Cannot read shipped directive file %s: %s; skipping",
                    src_path,
                    exc,
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_text(content, encoding="utf-8")
            except OSError as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Cannot write shipped directive file %s: %s; skipping",
                    target,
                    exc,
                )
                continue
            created.append(target)
    return created


def _walk_traversable(root) -> list:
    """遍历一个 Traversable（``importlib.resources``）目录树。

    返回 ``root`` 下每个文件（相对路径以 ``Traversable`` 形式）。
    目录先于其下文件产出，让调用方可以先 mkdir 父路径。
    """

    out: list = []
    try:
        children = list(root.iterdir())
    except (OSError, NotImplementedError):
        return out

    # 排序以保证确定性播种顺序。
    children.sort(key=lambda p: p.name)
    for child in children:
        try:
            if child.is_dir():
                out.extend(_walk_traversable(child))
            else:
                out.append(child)
        except (OSError, NotImplementedError):
            # 部分 Traversables 无法回答 ``is_dir()``；按文件处理
            out.append(child)
    return out


def _genre_scaffolding(root: Path, canonical_genre: str) -> list[Path]:
    """创建题材特定的文件并返回实际写入的路径列表。

    返回列表只包含实际写入的路径；已存在的文件保持不变。
    ``canonical_genre`` 必须是 ``{历史, 言情, 玄幻, other}`` 之一
    （:func:`_normalize_genre` 返回的白名单）；``other`` 返回 ``[]``。
    """
    scaffolds: dict[str, dict[Path, str]] = {
        "历史": {
            root / "史实" / "年表.md": "# 年表\n\n按年份记录关键历史事件。\n",
            root / "史实" / "人物.md": "# 历史人物\n\n记录涉及的关键历史人物。\n",
            root / "史实" / "事件.md": "# 重大事件\n\n记录重大历史事件及其时间顺序。\n",
            root / "史实" / "考证.md": "# 考证备忘\n\n史实资料的核实状态与争议说明。\n",
        },
        "玄幻": {
            root / "伏笔" / "foreshadow.md": (
                "# 伏笔表\n\n记录伏笔编号、内容、计划回收章节。\n"
            ),
            root / "大纲" / "境界表.md": (
                "# 境界表\n\n记录修炼等级体系与各境界节点。\n"
            ),
        },
        "言情": {
            root / "人设" / "男主.md": "# 男主人设\n\n",
            root / "人设" / "女主.md": "# 女主人设\n\n",
            root / "大纲" / "感情线时间轴.md": (
                "# 感情线时间轴\n\n按关系阶段拆章。\n"
            ),
        },
    }

    mapping = scaffolds.get(canonical_genre)
    if not mapping:
        return []

    created: list[Path] = []
    for path, content in mapping.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)
    return created


def _normalize_name(name: str) -> str:
    normalized = name.strip().replace(" ", "-")
    if not normalized:
        msg = (
            "项目名称不能为空。"
            "请传入至少一个非空白字符，例如 `writer init 我的小说`。"
        )
        raise ValueError(msg)
    return normalized


__all__ = [
    "NovelWorkspace",
    "create_new_workspace",
    "create_workspace",
]
