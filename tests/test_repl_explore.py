"""Tests for the REPL ``/start`` command.

per 2026-07-23: ``/init <故事梗概>`` 形式已废弃。启动 explore 多轮创作
改用 ``/start``,从 ``创意/简介.md`` 读取用户主动填写的核心创意。

历史:本文件原为 ``test_repl_init_explore_*`` 系列,覆盖 ``_try_handle_repl_init_explore``
REPL pre-hook。新流程下 ``/start`` 走 ``_handle_repl_start`` helper。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from writer.session import Engine

# ---------------------------------------------------------------------------
# REPL ``/start`` explore mode
# ---------------------------------------------------------------------------


def test_repl_start_creates_scaffold_and_writes_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常路径:``简介.md`` 有内容 + 有 API Key → 跑 explore → 落盘。"""

    from langchain_core.messages import AIMessage

    import writer.cli.repl as repl
    from writer.config import Settings

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n## 当前状态\n\n- state: S1\n",
        encoding="utf-8",
    )
    (project / "创意").mkdir()
    (project / "创意" / "简介.md").write_text(
        "# 核心创意\n\n程序员林渊穿越到唐朝对抗邪恶势力。\n",
        encoding="utf-8",
    )
    session = Engine()
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

    assert repl.handle_repl_input("/start", session)
    assert (project / "创意" / "核心创意.md").is_file()
    assert (project / "大纲" / "写作架构.md").is_file()
    assert "- 题材: 历史" in (project / "AGENT.md").read_text(encoding="utf-8")


def test_repl_start_rejects_without_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 API Key:``/start`` 拒绝并提示用户配置 API Key。"""

    import writer.cli.repl as repl
    from writer.config import Settings

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n", encoding="utf-8")
    (project / "创意").mkdir()
    (project / "创意" / "简介.md").write_text(
        "主角林渊穿越到唐朝。", encoding="utf-8"
    )

    session = Engine()
    session.set_project_root(project)

    monkeypatch.setattr(repl, "get_settings", lambda: Settings(api_key=None))

    assert repl.handle_repl_input("/start", session)
    assert not (project / "创意" / "核心创意.md").exists()


def test_repl_start_rejects_when_brief_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``简介.md`` 不存在:``/start`` 红色提示。"""

    import writer.cli.repl as repl
    from writer.config import Settings

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n", encoding="utf-8")

    session = Engine()
    session.set_project_root(project)

    monkeypatch.setattr(repl, "get_settings", lambda: Settings(api_key="sk-test"))

    assert repl.handle_repl_input("/start", session)
    assert not (project / "创意" / "核心创意.md").exists()


def test_repl_start_rejects_when_brief_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``简介.md`` 空白:``/start`` 红色提示内容为空。"""

    import writer.cli.repl as repl
    from writer.config import Settings

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n", encoding="utf-8")
    (project / "创意").mkdir()
    (project / "创意" / "简介.md").write_text("   \n\n", encoding="utf-8")

    session = Engine()
    session.set_project_root(project)

    monkeypatch.setattr(repl, "get_settings", lambda: Settings(api_key="sk-test"))

    assert repl.handle_repl_input("/start", session)
    assert not (project / "创意" / "核心创意.md").exists()


def test_repl_start_rejects_extra_args(
    tmp_path: Path,
) -> None:
    """``/start <额外参数>`` 拒绝并提示用户改用编辑器写 ``简介.md``。"""

    import writer.cli.repl as repl

    project = tmp_path / "novel"
    project.mkdir()

    session = Engine()
    session.set_project_root(project)

    assert repl.handle_repl_input("/start 一个穿越到唐朝的程序员", session)
    # 不该创建任何项目 / 跑 explore
    assert not (project / "创意" / "核心创意.md").exists()


def test_repl_start_rejects_without_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 project_root + cwd 不在项目目录:``/start`` 提示用户先 ``writer new``。"""

    import writer.cli.repl as repl

    monkeypatch.chdir(tmp_path)

    session = Engine()  # 不绑定 project_root
    assert repl.handle_repl_input("/start", session)


__all__ = []
