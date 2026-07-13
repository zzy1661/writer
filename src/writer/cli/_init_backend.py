"""init 共享后端：``init_project`` / ``_maybe_apply_init_brief`` /
``apply_genre_and_brief``。

把 ``writer new``（Typer ``new`` 子命令）与 REPL ``/init --flag``
共用的项目初始化逻辑独立成模块，让 ``commands`` 与 ``repl`` 都
依赖这个统一入口而不直接依赖彼此。``writer.cli.repl.console``
作为共享的 Rich Console 单例被复用。

``apply_genre_and_brief`` 是 REPL 简洁 ``/init <brief>`` 形式的
专用后端：复用 :func:`writer.project.init_brief.apply_init_brief`
写 brief，并把「补建题材脚手架 + 更新 ``题材:`` 行」两步前置，
让后续 brief 流程写下的 ``## 基本要求`` 段总是排在题材行之后
（语义稳定）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from writer.cli.repl import console
from writer.config import get_settings, load_project_settings, refresh_settings
from writer.project import (
    apply_genre_scaffolding,
    create_workspace,
    normalize_genres,
    update_agent_genre_line,
)
from writer.project.init_brief import apply_init_brief

if TYPE_CHECKING:
    from writer.config import Settings


def init_project(
    name: str,
    directory: Path,
    *,
    force: bool = False,
    genre: str | None = None,
    genres: list[str] | None = None,
    brief: str | None = None,
    skip_brief: bool = False,
) -> str:
    """Typer ``init`` 子命令与 REPL ``/init`` 共用的后端。

    返回使用的规范题材标签（用于 session 绑定）。
    """
    genre_list = normalize_genres(genres if genres is not None else ([genre] if genre else ["other"]))
    from writer.project.genre import format_genre_line, primary_genre

    resolved_genre = format_genre_line(genre_list) or primary_genre(genre_list)
    try:
        workspace = create_workspace(
            name,
            directory,
            force=force,
            genres=genre_list,
            with_ideas_dir=True,
        )
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建小说项目：[/green]{workspace.root}")
    console.print(f"题材：{resolved_genre}")
    for path in workspace.created_files:
        console.print(f"  - {path}")

    _maybe_apply_init_brief(
        workspace.root, brief=brief, skip_brief=skip_brief, genre=resolved_genre
    )

    console.print(
        "[dim]提示：在同一目录执行 `uv run writer` 进入 REPL 时会自动绑定此项目。[/dim]"
    )
    return resolved_genre


def _maybe_apply_init_brief(
    project_root: Path,
    *,
    brief: str | None,
    skip_brief: bool,
    genre: str,
) -> None:
    if skip_brief:
        return

    user_brief = brief
    if user_brief is None and sys.stdin.isatty():
        console.print(
            "\n[cyan]请用自然语言描述你的小说创意与基本要求[/cyan]"
            "（直接回车跳过）："
        )
        user_brief = typer.prompt("", default="", show_default=False)

    if not user_brief or not user_brief.strip():
        return

    load_project_settings(project_root)
    refresh_settings()
    # ``process_init_brief``（``chg-remove-roles`` 后唯一幸存的
    # Python-side 能力）通过 :func:`writer.project.init_brief.apply_init_brief`
    # 调用；不需要 ``deps.story_agent``。
    result = apply_init_brief(project_root, user_brief.strip(), settings=get_settings())
    console.print(f"[green]已写入 创意/核心创意.md[/green]（来源: {result.source}）")
    console.print("[green]已更新 AGENT.md 基本要求[/green]")


@dataclass(frozen=True)
class InitBriefOutcome:
    """``apply_genre_and_brief`` 一步完成的产物摘要。"""

    project_root: Path
    selected_genres: list[str]
    created_files: list[Path]
    genre_line_changed: bool
    brief_source: str  # ``"llm"`` 或 ``"fallback"``


def apply_genre_and_brief(
    project_root: Path,
    *,
    genres: list[str],
    brief: str,
    settings: Settings,
    llm=None,
) -> InitBriefOutcome:
    """对已存在项目一次性完成：补建题材脚手架 + 更新题材行 + 写 brief。

    步骤顺序固定（题材行 → 基本要求段）：

    1. :func:`apply_genre_scaffolding` —— 为 ``genres`` 中每个白名单
       题材补建对应子目录 / 文件；已存在文件保留（additive）。
    2. :func:`update_agent_genre_line` —— 局部更新 ``AGENT.md``
       中的 ``题材:`` 行，不重写其它段（``## 基本要求`` 等保留）。
       步骤 1 与 2 即使无变更也是幂等 no-op。
    3. :func:`writer.project.init_brief.apply_init_brief` —— 写
       ``创意/核心创意.md`` + 追加 ``## 基本要求`` 段。此时题材行
       已经定位好，``append_agent_requirements`` 把新段追加在
       AGENT.md 末尾（题材行之后）。

    ``genres`` 会先经 :func:`normalize_genres` 规范化（去重、别名映射）；
    ``brief`` 必须非空（调用方负责检测）。

    ``llm=None`` 走 :func:`writer.project.init_brief.apply_init_brief`
    的 deterministic Markdown 兜底（``source="fallback"``）；有 API
    key 时传 ``settings`` 让其内部按 ``invoke_structured_json`` 走 LLM。
    """

    genre_list = normalize_genres(genres)
    created = apply_genre_scaffolding(project_root, genre_list)
    genre_line_changed = update_agent_genre_line(
        project_root / "AGENT.md", genre_list
    )

    load_project_settings(project_root)
    refresh_settings()
    result = apply_init_brief(
        project_root, brief, settings=settings, llm=llm
    )

    return InitBriefOutcome(
        project_root=project_root,
        selected_genres=genre_list,
        created_files=created,
        genre_line_changed=genre_line_changed,
        brief_source=result.source,
    )


__all__ = [
    "InitBriefOutcome",
    "apply_genre_and_brief",
    "init_project",
]
