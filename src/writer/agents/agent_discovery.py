"""项目级与内置 agent 发现。

公开 API（per ``fea-agent-mirror``）：

* :func:`discover_agents` —— 扫描项目的
  ``<project_root>/.writer/agents/*.md`` 文件，并加载每个格式良好的
  :class:`Agent`。
* :func:`discover_shipped_agents` —— 通过 ``importlib.resources`` 列出
  位于 ``writer/agents/_shipped/`` 的 4 个内置 agent。
* :func:`discover_entry_point_agents` —— entry-point 插件钩子。

所有失败以 WARNING 记录并跳过 —— 一个损坏的 agent *不得* 阻止其他
agent 加载，*也不得* 阻止 REPL 启动。
"""

from __future__ import annotations

import importlib.resources
import logging
import re
from importlib import metadata
from pathlib import Path

log = logging.getLogger(__name__)


#: Frontmatter 模式：``---\n<yaml>---\n<body>``。要求两个分隔符都
#: 存在（文件必须是完整的 YAML 文档）。支持多行 frontmatter；
#: 闭合的 ``---`` 必须独占一行。
_FRONTMATTER_PATTERN = re.compile(
    r"\A---\s*\n(?P<front>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)


def discover_agents(project_root: Path) -> list[object]:
    """发现并加载项目级 agent。

    扫描 ``<project_root>/.writer/agents/*.md``（*不*是每个 agent 一个
    子目录 —— agent 是顶层扁平 ``.md`` 文件，镜像 Claude Code 的
    ``.claude/agents/`` 布局）。隐藏文件（``_draft`` / ``.hidden``）
    和没有合法 YAML frontmatter 的文件会被静默跳过（并 WARNING）。
    """

    agents: list[object] = []
    agents_dir = (project_root / ".writer" / "agents").resolve()
    if not agents_dir.is_dir():
        return agents

    try:
        candidates = sorted(p for p in agents_dir.iterdir() if p.is_file())
    except OSError as exc:
        log.warning(
            "Cannot enumerate project agents at %s: %s; "
            "continuing without project layer",
            agents_dir,
            exc,
        )
        return agents

    for path in candidates:
        basename = path.name
        if basename.startswith("_") or basename.startswith("."):
            log.debug("Skipping non-public project agent: %s", path)
            continue
        if not basename.endswith(".md"):
            log.debug("Skipping non-md project agent file: %s", path)
            continue
        agent = _parse_agent_file(path)
        if agent is not None:
            agents.append(agent)
    return agents


def discover_shipped_agents() -> list[object]:
    """发现位于 ``writer.agents._shipped/<name>.md`` 的 4 个内置 agent。

    使用 ``importlib.resources.files()`` 让 loader 在 wheel 安装、
    sdist 安装或源码 checkout 直接 import 时都能工作。
    """

    agents: list[object] = []
    try:
        # Python 3.12+：``files()`` 返回 ``Traversable``。
        root = importlib.resources.files("writer.agents._shipped")
    except Exception as exc:  # noqa: BLE001 — 打包环境差异较大
        log.warning(
            "Cannot locate shipped agents package: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return agents

    try:
        file_iter = sorted(
            (p for p in root.iterdir() if p.name.endswith(".md")),
            key=lambda p: p.name,
        )
    except (OSError, NotImplementedError) as exc:
        log.warning(
            "Cannot iterate shipped agents: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return agents

    for traversable in file_iter:
        agent = _parse_traversable_agent(traversable)
        if agent is not None:
            agents.append(agent)
    return agents


def discover_entry_point_agents() -> list[object]:
    """通过 Python entry points 发现已注册的 agent。

    插件通过在 ``pyproject.toml`` 的
    ``[project.entry-points."writer.agents"]`` 增加条目来注册
    agent：

    .. code-block:: toml

       [project.entry-points."writer.agents"]
       my_agent = "my_pkg.my_mod:MyAgent"

    每个 entry point 可解析为：

    * :class:`Agent` 类 —— 以无参方式实例化；
    * 预先构造好的 :class:`Agent` 实例 —— 直接使用。

    任何解析失败（distribution 缺失、import 错误、属性错误、schema
    无效）都以 WARNING 记录并跳过，让损坏的插件永远不阻塞 REPL 启动。
    """

    from writer.agents.protocol import Agent  # noqa: PLC0415
    from writer.agents.registry import AgentRegistryError, _validate  # noqa: PLC0415

    discovered: list[object] = []
    try:
        entries = metadata.entry_points(group="writer.agents")
    except Exception:  # noqa: BLE001
        log.warning(
            "Agent entry_points discovery failed; continuing without plugins"
        )
        return discovered

    for entry in entries:
        try:
            target = entry.load()
        except Exception:  # noqa: BLE001
            log.warning(
                "Failed to import agent entry point %s=%s; skipping",
                entry.name,
                entry.value,
            )
            continue

        try:
            if isinstance(target, type):
                instance: object = target()
            elif isinstance(target, Agent):
                instance = target
            else:
                log.warning(
                    "Agent entry point %s did not resolve to an Agent "
                    "(got %s); skipping",
                    entry.name,
                    type(target).__name__,
                )
                continue
        except Exception:  # noqa: BLE001
            log.warning(
                "Agent entry point %s constructor raised; skipping",
                entry.name,
            )
            continue

        try:
            _validate(instance)
        except AgentRegistryError as exc:
            log.warning("Agent entry point %s rejected: %s", entry.name, exc)
            continue

        discovered.append(instance)
    return discovered


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_agent_file(path: Path) -> object:
    """解析常规文件系统上的一个 agent ``.md`` 文件。

    作为顶层辅助函数暴露，让测试可以直接调用。schema 错误（缺少
    必填键、body 为空、name 不合法）时抛
    :class:`writer.agents.registry.AgentRegistryError`。
    """

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot read agent file at {path}: {exc}"
        raise AgentRegistryError(msg) from exc

    return _build_agent_from_text(text, root=path.resolve())


def _parse_agent_file(path: Path) -> object | None:
    """失败时记 log 的包装（供发现循环使用）。"""

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        return parse_agent_file(path)
    except AgentRegistryError as exc:
        log.warning("Agent file at %s rejected: %s; skipping", path, exc)
        return None


def _parse_traversable_agent(traversable) -> object | None:
    """解析通过 ``importlib.resources`` 访问的一个内置 agent ``.md``。

    ``importlib.resources`` 返回 ``Traversable`` 对象（不是真实路径）。
    我们通过 ``.read_text(encoding='utf-8')`` 读取，并把字符串化的
    路径作为 agent 的 ``root``。
    """

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        text = traversable.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning(
            "Cannot read shipped agent at %s: %s; skipping",
            traversable,
            exc,
        )
        return None

    try:
        return _build_agent_from_text(text, root=Path(str(traversable)))
    except AgentRegistryError as exc:
        log.warning(
            "Shipped agent at %s rejected: %s; skipping",
            traversable,
            exc,
        )
        return None


def _build_agent_from_text(text: str, *, root: Path) -> object:
    """从原始 ``.md`` 文本 + root 路径构造一个 :class:`Agent`。

    任何 schema 违反抛 :class:`AgentRegistryError`。
    """

    from writer.agents.protocol import Agent  # noqa: PLC0415
    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    parsed = _parse_frontmatter_and_body(text)
    if parsed is None:
        msg = f"agent file at {root} has invalid frontmatter envelope"
        raise AgentRegistryError(msg)
    front, body = parsed

    meta = _validate_frontmatter(front, source=str(root))
    return Agent(
        name=meta["name"],
        description=meta["description"],
        genre=meta["genre"],
        body=body.rstrip("\n"),
        tools_allowlist=meta["tools_allowlist"],
        root=root,
    )


def _parse_frontmatter_and_body(text: str) -> tuple[str, str] | None:
    """从 agent 文件中抽取 YAML frontmatter 和 Markdown body。"""

    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        return None
    return match["front"], match["body"]


def _validate_frontmatter(front_str: str, *, source: str) -> dict:
    """解析并校验 YAML frontmatter。抛 :class:`AgentRegistryError`。"""

    import yaml  # local import: top-level yaml import is heavy

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        data = yaml.safe_load(front_str)
    except yaml.YAMLError as exc:
        msg = f"YAML parse error in {source}: {exc}"
        raise AgentRegistryError(msg) from exc

    if not isinstance(data, dict):
        msg = f"frontmatter in {source} must be a mapping; got {type(data).__name__}"
        raise AgentRegistryError(msg)

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        msg = f"frontmatter in {source}: `name` must be a non-empty string"
        raise AgentRegistryError(msg)

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        msg = f"frontmatter in {source}: `description` must be a non-empty string"
        raise AgentRegistryError(msg)
    description = description.strip()
    if not (50 <= len(description) <= 500):
        msg = (
            f"frontmatter in {source}: `description` length must be 50-500 "
            f"chars; got {len(description)}"
        )
        raise AgentRegistryError(msg)

    genre = data.get("genre")
    if not isinstance(genre, str) or not genre.strip():
        msg = f"frontmatter in {source}: `genre` must be a non-empty string"
        raise AgentRegistryError(msg)

    raw_tools = data.get("tools", [])
    if raw_tools is None:
        raw_tools = []
    if not isinstance(raw_tools, list) or not all(
        isinstance(t, str) for t in raw_tools
    ):
        msg = f"frontmatter in {source}: `tools` must be a list of strings"
        raise AgentRegistryError(msg)

    return {
        "name": name.strip(),
        "description": description,
        "genre": genre.strip(),
        "tools_allowlist": tuple(raw_tools),
    }


__all__ = [
    "discover_agents",
    "discover_shipped_agents",
    "discover_entry_point_agents",
    "parse_agent_file",
]
