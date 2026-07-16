"""Tests for the REPL explore initialization entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

from writer.session import EngineSession

# REPL ``/init <brief>`` explore mode
# ---------------------------------------------------------------------------


def test_repl_init_explore_creates_scaffold_and_writes_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.messages import AIMessage

    import writer.cli.repl as repl
    from writer.config import Settings

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n## 当前状态\n\n- state: S1\n",
        encoding="utf-8",
    )
    session = EngineSession()
    session.set_project_root(project)

    class _FakeExploreChat:
        def invoke(self, messages: object) -> AIMessage:
            return AIMessage(
                content=(
                    '{"status":"completed","outcome":'
                    '{"core_idea":"# 扩写核心创意",'
                    '"requirements":"- 篇幅: 长篇",'
                    '"genres":["历史"],"architecture":"三幕结构"}}'
                )
            )

    monkeypatch.setattr(repl, "get_settings", lambda: Settings(api_key="sk-test"))
    monkeypatch.setattr(repl, "get_llm", lambda settings: _FakeExploreChat())
    monkeypatch.setattr(repl, "_confirm_recommended_genre", lambda label: True)

    assert repl.handle_repl_input("/init 一个程序员穿越到唐朝对抗邪恶势力的故事。", session)
    assert (project / "创意" / "核心创意.md").is_file()
    assert (project / "大纲" / "写作架构.md").is_file()
    assert "- 题材: 历史" in (project / "AGENT.md").read_text(encoding="utf-8")


def test_repl_init_explore_rejects_without_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import writer.cli.repl as repl
    from writer.config import Settings

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n", encoding="utf-8")
    session = EngineSession()
    session.set_project_root(project)

    monkeypatch.setattr(repl, "get_settings", lambda: Settings(api_key=None))

    assert repl.handle_repl_input("/init 一个程序员穿越到唐朝对抗邪恶势力的故事。", session)
    assert not (project / "创意" / "核心创意.md").exists()


def test_repl_init_explore_returns_false_for_non_brief(
    tmp_path: Path,
) -> None:
    import writer.cli.repl as repl

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n", encoding="utf-8")
    session = EngineSession()
    session.set_project_root(project)

    assert repl._try_handle_repl_init_explore("/init 双生", session) is False


__all__ = []
