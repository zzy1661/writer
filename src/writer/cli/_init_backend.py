"""init 共享后端：``apply_genre_and_brief``。

REPL 简洁 ``/init <创意>`` 形式的专用后端：复用
:func:`writer.project.init_brief.apply_init_brief` 写 brief,并把
「补建题材脚手架 + 更新 ``题材:`` 行」两步前置,让后续 brief 流程
写下的 ``## 基本要求`` 段总是排在题材行之后(语义稳定)。

``writer new`` 子命令(Typer 层)现在直接调 :func:`create_new_workspace`,
不再经此模块 —— REPL ``/init --name X --dir Y`` flag 形式已于
2026-07-14 删除(创建项目请用 CLI 子命令)。

``writer.cli.repl.console`` 作为共享的 Rich Console 单例被复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from writer.config import load_project_settings, refresh_settings
from writer.project import (
    apply_genre_scaffolding,
    normalize_genres,
    update_agent_genre_line,
)
from writer.project.init_brief import apply_init_brief

if TYPE_CHECKING:
    from writer.config import Settings


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
    """对已存在项目一次性完成:补建题材脚手架 + 更新题材行 + 写 brief。

    步骤顺序固定(题材行 → 基本要求段):

    1. :func:`apply_genre_scaffolding` —— 为 ``genres`` 中每个白名单
       题材补建对应子目录 / 文件;已存在文件保留(additive)。
    2. :func:`update_agent_genre_line` —— 局部更新 ``AGENT.md``
       中的 ``题材:`` 行,不重写其它段(``## 基本要求`` 等保留)。
       步骤 1 与 2 即使无变更也是幂等 no-op。
    3. :func:`writer.project.init_brief.apply_init_brief` —— 写
       ``创意/核心创意.md`` + 追加 ``## 基本要求`` 段。此时题材行
       已经定位好,``append_agent_requirements`` 把新段追加在
       AGENT.md 末尾(题材行之后)。

    ``genres`` 会先经 :func:`normalize_genres` 规范化(去重、别名映射);
    ``brief`` 必须非空(调用方负责检测)。

    ``llm=None`` 走 :func:`writer.project.init_brief.apply_init_brief`
    的 deterministic Markdown 兜底(``source="fallback"``);有 API
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
]
