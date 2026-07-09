"""post-init 创意梗概处理。"""

from __future__ import annotations

from pathlib import Path

from writer.agents import InitBriefResult, process_init_brief
from writer.config import Settings
from writer.project.state import ProjectState, append_agent_requirements, detect_state

_SENTENCE_PUNCTUATION = "。！？；,.!?;"
_MAX_PROJECT_NAME_LEN = 30


def extract_init_brief_text(user_input: str) -> str:
    """从一行 REPL ``/init ...`` 中返回梗概文本（可为空）。"""

    rest = user_input.removeprefix("/init").strip()
    if rest.startswith("--brief"):
        return rest.removeprefix("--brief").strip()
    if rest.startswith("-b "):
        return rest[3:].strip()
    return rest


def looks_like_creative_brief(text: str) -> bool:
    """启发式：参数看起来像故事概要而非目录名。"""

    normalized = text.strip()
    if not normalized:
        return False
    if normalized.startswith(("-", "--")):
        return normalized.startswith(("--brief", "-b "))
    if len(normalized) > _MAX_PROJECT_NAME_LEN:
        return True
    return any(char in normalized for char in _SENTENCE_PUNCTUATION)


def looks_like_project_name(text: str) -> bool:
    """启发式：适合作为 workspace 目录名的短 token。"""

    normalized = text.strip()
    if not normalized or normalized.startswith(("-", "--")):
        return False
    if len(normalized) > _MAX_PROJECT_NAME_LEN:
        return False
    if any(char in normalized for char in _SENTENCE_PUNCTUATION):
        return False
    return " " not in normalized and "\t" not in normalized


def should_run_init_brief(
    user_input: str,
    *,
    project_root: Path | None,
    project_state: str | ProjectState,
) -> bool:
    """``/init`` 是否应在已绑定项目上跑创意梗概流程。"""

    del project_state  # 已绑定时 ``detect_state(project_root)`` 是权威。

    rest = extract_init_brief_text(user_input)
    if not rest:
        return False

    raw_rest = user_input.removeprefix("/init").strip()
    if raw_rest.startswith(("--brief", "-b ")):
        return True

    return (
        project_root is not None
        and detect_state(project_root) == ProjectState.INITIALIZED
    )


def apply_init_brief(
    project_root: Path,
    brief: str,
    *,
    settings: Settings,
    llm=None,
) -> InitBriefResult:
    """把自然语言梗概展开并写入项目文件。

    Python-side 能力位于 :func:`writer.agents.process_init_brief`（per
    ``chg-remove-roles``：``writer.roles.StoryAgent`` 类在
    ``fea-agent-mirror`` 让其方法变成死代码后被删除）。
    """

    result = process_init_brief(brief, settings=settings, llm=llm)
    ideas_dir = project_root / "创意"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    (ideas_dir / "核心创意.md").write_text(result.core_idea, encoding="utf-8")
    append_agent_requirements(project_root / "AGENT.md", result.requirements)
    return result


__all__ = [
    "apply_init_brief",
    "extract_init_brief_text",
    "looks_like_creative_brief",
    "looks_like_project_name",
    "should_run_init_brief",
]
