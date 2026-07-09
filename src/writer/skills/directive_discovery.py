"""项目级与内置 directive 发现。

公开 API（per chg-markdown-skills）：

* :func:`discover_directives` —— 扫描项目的
  ``<project_root>/.writer/skills/*/SKILL.md`` 目录，并加载
  每个格式良好的 ``SkillDirective``。
* :func:`discover_shipped_directives` —— 通过 ``importlib.resources``
  列出位于 ``src/writer/skills/_shipped/`` 的 4 个内置 directives。
* :func:`discover_entry_point_directives` —— entry-point 插件钩子
  （镜像原先 ``discover_entry_point_skills`` 的策略）。

所有失败以 WARNING 记录并跳过 —— 一个损坏的 directive *不得* 阻止
其他 directives 加载，*也不得* 阻止 REPL 启动。这与原先
``discover_entry_point_skills`` 的行为逐字一致。
"""

from __future__ import annotations

import importlib.resources
import importlib.util
import logging
import re
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from writer.skills.errors import SkillError
from writer.skills.protocol import SkillDirective

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


#: Frontmatter 模式：``---\n<yaml>---\n<body>``。要求两个分隔符都
#: 存在（文件必须是完整的 YAML 文档）。支持多行 frontmatter；
#: 闭合的 ``---`` 必须独占一行。
_FRONTMATTER_PATTERN = re.compile(
    r"\A---\s*\n(?P<front>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)

#: SKILL.md body 内的 ``@reference path/to/file.md`` 引用。
#: 捕获 ``@reference`` 与空白或行尾之间的相对路径（不含空白）。
_REFERENCE_PATTERN = re.compile(r"@reference\s+(?P<path>[^\s]+)")


def discover_directives(project_root: Path) -> list[SkillDirective]:
    """发现并加载项目级 directives。

    扫描 ``<project_root>/.writer/skills/*/SKILL.md``，返回按命令
    排序的已校验 :class:`SkillDirective` 实例列表，保证顺序确定性。

    隐藏目录（``_draft`` / ``.hidden``）和没有 ``SKILL.md`` 文件的
    条目会被静默跳过。
    """

    directives: list[SkillDirective] = []
    skills_dir = (project_root / ".writer" / "skills").resolve()
    if not skills_dir.is_dir():
        return directives

    try:
        candidates = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    except OSError as exc:
        log.warning(
            "Cannot enumerate project directives at %s: %s; "
            "continuing without project layer",
            skills_dir,
            exc,
        )
        return directives

    for sub in candidates:
        basename = sub.name
        if basename.startswith("_") or basename.startswith("."):
            log.debug("Skipping non-public project directive: %s", sub)
            continue
        skill_md = sub / "SKILL.md"
        if not skill_md.is_file():
            log.debug("Skipping directory without SKILL.md: %s", sub)
            continue
        directive = _parse_skill_md(skill_md)
        if directive is not None:
            directives.append(directive)
    return directives


def discover_shipped_directives() -> list[SkillDirective]:
    """发现位于 ``writer.skills._shipped/<command>/SKILL.md`` 的
    4 个内置 directives。

    使用 ``importlib.resources.files()`` 让 loader 在 wheel 安装、
    sdist 安装或源码 checkout 直接 import 时都能工作。
    """

    directives: list[SkillDirective] = []
    try:
        # Python 3.12+：``files()`` 返回 ``Traversable``。
        root = importlib.resources.files("writer.skills._shipped")
    except Exception as exc:  # noqa: BLE001 — 打包环境差异较大
        log.warning(
            "Cannot locate shipped directives package: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return directives

    try:
        sub_iter = sorted(
            (p for p in root.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
    except (OSError, NotImplementedError) as exc:
        log.warning(
            "Cannot iterate shipped directives: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return directives

    for sub in sub_iter:
        skill_md = sub / "SKILL.md"
        directive = _parse_traversable_skill_md(skill_md)
        if directive is not None:
            directives.append(directive)
    return directives


def discover_entry_point_directives() -> list[SkillDirective]:
    """通过 Python entry points 发现已注册的 directives。

    插件通过在 ``pyproject.toml`` 的
    ``[project.entry-points."writer.directives"]`` 增加条目来注册
    directives：

    .. code-block:: toml

       [project.entry-points."writer.directives"]
       my_directive = "my_pkg.my_mod:MyDirective"

    每个 entry point 可解析为：

    * :class:`SkillDirective` 类 —— 以无参方式实例化；
    * 预先构造好的 :class:`SkillDirective` 实例 —— 直接使用。

    任何解析失败（distribution 缺失、import 错误、属性错误、schema
    无效）都以 WARNING 记录并跳过，让损坏的插件永远不阻塞 REPL 启动。
    """

    discovered: list[SkillDirective] = []
    try:
        entries = metadata.entry_points(group="writer.directives")
    except Exception:  # noqa: BLE001
        log.warning(
            "Directive entry_points discovery failed; continuing without plugins"
        )
        return discovered

    for entry in entries:
        try:
            target = entry.load()
        except Exception:  # noqa: BLE001
            log.warning(
                "Failed to import directive entry point %s=%s; skipping",
                entry.name,
                entry.value,
            )
            continue

        try:
            if isinstance(target, type):
                instance = target()
            elif isinstance(target, SkillDirective):
                instance = target
            else:
                log.warning(
                    "Directive entry point %s did not resolve to a SkillDirective "
                    "(got %s); skipping",
                    entry.name,
                    type(target).__name__,
                )
                continue
        except Exception:  # noqa: BLE001
            log.warning(
                "Directive entry point %s constructor raised; skipping",
                entry.name,
            )
            continue

        try:
            _validate(instance)
        except SkillError as exc:
            log.warning("Directive entry point %s rejected: %s", entry.name, exc)
            continue

        discovered.append(instance)
    return discovered


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_skill_md(skill_md_path: Path) -> SkillDirective | None:
    """解析常规文件系统上的一个 ``SKILL.md`` 文件。"""

    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning(
            "Cannot read SKILL.md at %s: %s; skipping",
            skill_md_path,
            exc,
        )
        return None

    parsed = _parse_frontmatter_and_body(text)
    if parsed is None:
        log.warning(
            "SKILL.md at %s has invalid frontmatter; skipping",
            skill_md_path,
        )
        return None
    front, body = parsed

    try:
        meta = _validate_frontmatter(front)
    except SkillError as exc:
        log.warning("SKILL.md at %s rejected: %s; skipping", skill_md_path, exc)
        return None

    references = _load_references(skill_md_path.parent)
    scripts = _list_scripts(skill_md_path.parent)

    return SkillDirective(
        command=meta["command"],
        description=meta["description"],
        requires_states=meta["requires_states"],
        body=body.rstrip("\n"),
        references=references,
        scripts=scripts,
        root=skill_md_path.parent.resolve(),
    )


def _parse_traversable_skill_md(traversable) -> SkillDirective | None:
    """解析通过 ``importlib.resources`` 访问的一个内置 SKILL.md。

    ``importlib.resources`` 返回 ``Traversable`` 对象（不是真实路径）。
    我们通过 ``.read_text(encoding='utf-8')`` 读取，并把父
    ``Traversable``（而非 ``Path``）传给 references loader，
    让同一段代码对常规文件系统和包资源都能工作。
    """

    try:
        text = traversable.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning(
            "Cannot read shipped SKILL.md at %s: %s; skipping",
            traversable,
            exc,
        )
        return None

    parsed = _parse_frontmatter_and_body(text)
    if parsed is None:
        log.warning(
            "Shipped SKILL.md at %s has invalid frontmatter; skipping",
            traversable,
        )
        return None
    front, body = parsed

    try:
        meta = _validate_frontmatter(front)
    except SkillError as exc:
        log.warning(
            "Shipped SKILL.md at %s rejected: %s; skipping",
            traversable,
            exc,
        )
        return None

    references = _load_traversable_references(traversable.parent)
    scripts = _list_traversable_scripts(traversable.parent)

    # 对内置 directives，``root`` 是 Traversable —— 我们保留其字符串
    # 化路径，让下游代码仍能记录它。引擎不为内置 directives 执行脚本
    # （它们只作为引用模板被播种）。
    return SkillDirective(
        command=meta["command"],
        description=meta["description"],
        requires_states=meta["requires_states"],
        body=body.rstrip("\n"),
        references=references,
        scripts=scripts,
        root=Path(str(traversable.parent)),
    )


def _parse_frontmatter_and_body(text: str) -> tuple[str, str] | None:
    """从 SKILL.md 文件中抽取 YAML frontmatter 和 Markdown body。

    返回 ``(frontmatter_str, body_str)``，若文件没有正确的
    ``---\n...\n---\n`` 包络则返回 ``None``。
    """

    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        return None
    return match["front"], match["body"]


def _validate_frontmatter(front_str: str) -> dict:
    """解析并校验 YAML frontmatter。抛 ``SkillError``。"""

    import yaml  # local import: top-level yaml import is heavy

    try:
        data = yaml.safe_load(front_str)
    except yaml.YAMLError as exc:
        msg = f"YAML parse error: {exc}"
        raise SkillError(msg) from exc

    if not isinstance(data, dict):
        msg = "frontmatter must be a mapping"
        raise SkillError(msg)

    command = data.get("command")
    if not isinstance(command, str) or not command.startswith("/"):
        msg = f"command must be a non-empty string starting with '/'; got {command!r}"
        raise SkillError(msg)

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        msg = "description must be a non-empty string"
        raise SkillError(msg)

    raw_states = data.get("requires_states", [])
    if isinstance(raw_states, str):
        raw_states = [raw_states]
    if not isinstance(raw_states, list) or not raw_states:
        msg = "requires_states must be a non-empty list"
        raise SkillError(msg)

    # 把 requires_states 字符串解析为 ProjectState enum 成员。
    # ProjectState 是 StrEnum，value 是规范的 S0..S5 字符串，NAME
    # 是人类可读标识符。我们接受两种形式，让 SKILL.md frontmatter
    # 可以选择更清楚的那个：
    #   ``requires_states: [INITIALIZED, HAS_OUTLINE]``  ← 名称形式
    #   ``requires_states: [S1, S2]``                    ← value 形式
    # 本地 import：避免每次 skills import 都强制加载 project.state。
    from writer.project.state import ProjectState  # noqa: PLC0415

    # 一次性构造 name → ProjectState 映射，用于 name-form 查找。
    name_to_state = {member.name: member for member in ProjectState}

    resolved_states: set = set()
    for raw in raw_states:
        if not isinstance(raw, str):
            msg = f"requires_states entries must be strings; got {type(raw).__name__}"
            raise SkillError(msg)
        if raw in name_to_state:
            resolved_states.add(name_to_state[raw])
            continue
        try:
            resolved_states.add(ProjectState(raw))
        except ValueError as exc:
            valid = sorted(s for s in ProjectState)
            msg = (
                f"requires_states entry {raw!r} is not a valid ProjectState; "
                f"expected one of {valid} (by name) or their S0..S5 values"
            )
            raise SkillError(msg) from exc

    return {
        "command": command,
        "description": description.strip(),
        "requires_states": frozenset(resolved_states),
    }


def _validate(directive: SkillDirective) -> None:
    """对 entry-point / 程序化构建的 directive 做轻量校验。"""

    if not isinstance(directive.command, str) or not directive.command.startswith("/"):
        msg = f"directive command must start with '/'; got {directive.command!r}"
        raise SkillError(msg)
    if not isinstance(directive.description, str) or not directive.description.strip():
        msg = "directive description must be a non-empty string"
        raise SkillError(msg)
    if not isinstance(directive.requires_states, frozenset) or not directive.requires_states:
        msg = "directive requires_states must be a non-empty frozenset"
        raise SkillError(msg)
    if not isinstance(directive.body, str):
        msg = "directive body must be a string"
        raise SkillError(msg)


def _load_references(skill_dir: Path) -> dict[str, str]:
    """加载 ``<skill_dir>/references/`` 下所有 ``*.md``。

    返回按相对路径为键的 ``{relpath: content}``。非 md 文件静默
    跳过；``references/`` 目录缺失时返回 ``{}``。
    """

    refs_dir = skill_dir / "references"
    if not refs_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(refs_dir.rglob("*.md")):
        try:
            rel = path.relative_to(refs_dir).as_posix()
        except ValueError:
            continue
        try:
            out[rel] = path.read_text(encoding="utf-8").rstrip("\n")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning(
                "Cannot read reference %s in %s: %s; skipping",
                path,
                skill_dir,
                exc,
            )
    return out


def _list_scripts(skill_dir: Path) -> list[str]:
    """列出 ``<skill_dir>/scripts/`` 下文件的相对路径。"""

    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return []
    out: list[str] = []
    for path in sorted(scripts_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(skill_dir).as_posix()
        except ValueError:
            continue
        out.append(rel)
    return out


def _load_traversable_references(parent_traversable) -> dict[str, str]:
    """从 ``Traversable``（importlib.resources）加载 references。"""

    refs_dir = parent_traversable / "references"
    try:
        if not refs_dir.is_dir():
            return {}
    except (OSError, NotImplementedError):
        return {}

    out: dict[str, str] = {}
    try:
        candidates = sorted(p for p in refs_dir.rglob("*.md"))
    except (OSError, NotImplementedError) as exc:
        log.warning("Cannot iterate references at %s: %s; skipping", refs_dir, exc)
        return out

    for path in candidates:
        try:
            rel = path.relative_to(refs_dir).as_posix()
        except ValueError:
            continue
        try:
            out[rel] = path.read_text(encoding="utf-8").rstrip("\n")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning(
                "Cannot read shipped reference %s: %s; skipping", path, exc
            )
    return out


def _list_traversable_scripts(parent_traversable) -> list[str]:
    """从 ``Traversable``（importlib.resources）列出 scripts。"""

    scripts_dir = parent_traversable / "scripts"
    try:
        if not scripts_dir.is_dir():
            return []
    except (OSError, NotImplementedError):
        return []

    out: list[str] = []
    try:
        candidates = sorted(scripts_dir.rglob("*"))
    except (OSError, NotImplementedError) as exc:
        log.warning("Cannot iterate scripts at %s: %s; skipping", scripts_dir, exc)
        return out

    for path in candidates:
        try:
            if not path.is_file():
                continue
        except (OSError, NotImplementedError):
            continue
        try:
            rel = path.relative_to(parent_traversable).as_posix()
        except ValueError:
            continue
        out.append(rel)
    return out


def resolve_references(body: str, references: dict[str, str]) -> list[tuple[str, str]]:
    """解析 directive body 中的 ``@reference path/to/file.md`` 引用。

    对 directive ``references`` 字典中存在的每个引用，返回
    ``[(relpath, content)]``。未知引用静默跳过 —— 引擎以 WARNING
    记录后继续。

    路径规范化：``references`` 键按相对于 ``references/`` 子目录存储
    （例如 ``template.md``），但 SKILL.md body 通常写完整路径
    （``references/template.md``）。查找时去掉 ``references/`` 前缀，
    让作者两种写法都能用。

    顺序：按引用在 body 中出现的顺序。去重：同一引用多次出现只保留一份。
    """

    if not references:
        return []

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for match in _REFERENCE_PATTERN.finditer(body):
        relpath = match["path"]
        # 同时支持 ``@reference template.md`` 和
        # ``@reference references/template.md`` 查同一个 ``template.md`` 键。
        normalized = (
            relpath[len("references/") :]
            if relpath.startswith("references/")
            else relpath
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        content = references.get(normalized)
        if content is None:
            log.warning(
                "Directive body references %r but it is not in references; skipping",
                relpath,
            )
            continue
        out.append((normalized, content))
    return out


__all__ = [
    "discover_directives",
    "discover_shipped_directives",
    "discover_entry_point_directives",
    "resolve_references",
]
