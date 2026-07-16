"""explore 结果的项目落盘后端。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from writer.explore.agent import ExploreOutcome
from writer.explore.architectures import ArchitectureSpec, lookup_architecture
from writer.project import apply_genre_scaffolding, normalize_genres, update_agent_genre_line
from writer.project.state import append_agent_requirements

if TYPE_CHECKING:
    from writer.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExploreApplyOutcome:
    """``apply_explore_outcome`` 写入项目后的摘要。"""

    project_root: Path
    selected_genres: list[str]
    created_files: list[Path]
    genre_line_changed: bool
    architecture_name: str


def _requirements_with_architecture(
    requirements: str,
    architecture: str,
    spec: ArchitectureSpec | None,
) -> str:
    description = f"（{spec.short_description}）" if spec is not None else ""
    line = f"- 写作架构: {architecture}{description}"
    normalized = requirements.strip()
    if f"写作架构: {architecture}" in normalized:
        return normalized
    if not normalized:
        return line
    return f"{normalized}\n{line}"


def apply_explore_outcome(
    project_root: Path,
    outcome: ExploreOutcome,
    *,
    settings: Settings,
) -> ExploreApplyOutcome:
    """把 explore 结果一次性写入已有小说项目。"""

    del settings  # 保持与其它 init 后端一致的调用契约；本函数不再调用 LLM。

    genre_list = normalize_genres(outcome.genres)
    created = apply_genre_scaffolding(project_root, genre_list)
    genre_line_changed = update_agent_genre_line(
        project_root / "AGENT.md", genre_list
    )

    ideas_dir = project_root / "创意"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    core_path = ideas_dir / "核心创意.md"
    core_existed = core_path.exists()
    core_path.write_text(outcome.core_idea, encoding="utf-8")
    if not core_existed:
        created.append(core_path)

    try:
        architecture_spec = lookup_architecture(outcome.architecture)
    except KeyError:
        architecture_spec = None
        log.warning("未知写作架构 %r，跳过大纲/写作架构.md", outcome.architecture)

    append_agent_requirements(
        project_root / "AGENT.md",
        _requirements_with_architecture(
            outcome.requirements, outcome.architecture, architecture_spec
        ),
    )

    if architecture_spec is not None:
        outline_dir = project_root / "大纲"
        outline_dir.mkdir(parents=True, exist_ok=True)
        architecture_path = outline_dir / "写作架构.md"
        architecture_existed = architecture_path.exists()
        architecture_path.write_text(architecture_spec.markdown, encoding="utf-8")
        if not architecture_existed:
            created.append(architecture_path)

    return ExploreApplyOutcome(
        project_root=project_root,
        selected_genres=genre_list,
        created_files=created,
        genre_line_changed=genre_line_changed,
        architecture_name=outcome.architecture,
    )


__all__ = ["ExploreApplyOutcome", "apply_explore_outcome"]
