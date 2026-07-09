"""Post-init creative brief processing."""

from __future__ import annotations

from pathlib import Path

from writer.project.state import ProjectState, append_agent_requirements, detect_state
from writer.roles import InitBriefResult, StoryAgent

_SENTENCE_PUNCTUATION = "。！？；,.!?;"
_MAX_PROJECT_NAME_LEN = 30


def extract_init_brief_text(user_input: str) -> str:
    """Return brief text from a REPL ``/init ...`` line (may be empty)."""

    rest = user_input.removeprefix("/init").strip()
    if rest.startswith("--brief"):
        return rest.removeprefix("--brief").strip()
    if rest.startswith("-b "):
        return rest[3:].strip()
    return rest


def looks_like_creative_brief(text: str) -> bool:
    """Heuristic: args read as a story pitch, not a directory name."""

    normalized = text.strip()
    if not normalized:
        return False
    if normalized.startswith(("-", "--")):
        return normalized.startswith(("--brief", "-b "))
    if len(normalized) > _MAX_PROJECT_NAME_LEN:
        return True
    return any(char in normalized for char in _SENTENCE_PUNCTUATION)


def looks_like_project_name(text: str) -> bool:
    """Heuristic: short token suitable as a workspace directory name."""

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
    """Whether ``/init`` should run the creative brief flow on the bound project."""

    del project_state  # ``detect_state(project_root)`` is authoritative when bound.

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
    agent: StoryAgent,
) -> InitBriefResult:
    """Expand a natural-language brief and write project files."""

    result = agent.process_init_brief(brief)
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
